"""LudusProvider: RangeProvider over the Ludus REST API (https://ludus.cloud).

Consumed API-only (AGPL boundary). Where Ludus has no endpoint (e.g. snapshot
rollback), we delegate to the engine-PVE client — the engine is ours anyway.
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

from .base import RangeState, RangeStatus, VMHandle
from .pve import PveClient

log = structlog.get_logger(__name__)

SNAP_POST_DEPLOY = "pentrain-postdeploy"


class LudusError(RuntimeError):
    pass


class LudusProvider:
    def __init__(self, base_url: str, api_key: str, pve: PveClient, *, verify_tls: bool = False):
        self._api_key = api_key
        self.pve = pve
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            verify=verify_tls,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    async def close(self) -> None:
        await self._client.aclose()
        await self.pve.close()

    async def _req(self, method: str, path: str, **kw) -> Any:
        r = await self._client.request(method, path, **kw)
        if r.status_code >= 400:
            raise LudusError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
        try:
            return r.json()
        except Exception:
            return r.text

    async def _try(self, method: str, *paths: str, **kw) -> Any:
        """Try candidate endpoints (API surface varies across Ludus versions)."""
        last: Exception | None = None
        for p in paths:
            try:
                return await self._req(method, p, **kw)
            except LudusError as e:
                last = e
                if "404" not in str(e):
                    raise
        raise last or LudusError("no endpoint candidates")

    # ---------------- RangeProvider ----------------

    async def deploy_range(self, name: str, config: dict, *, force: bool = False) -> str:
        await self._req("PUT", "/range/config", json=config)
        await self._req("POST", "/range/deploy", json={"tags": "all", "force": force})
        st = await self.status()
        # Never return `name` — it isn't a ludus rangeID and would poison later
        # status(rangeID=...) filters. "" → subsequent calls use the default range.
        return st.range_id or ""

    async def status(self, range_id: str | None = None) -> RangeStatus:
        params = {"rangeID": range_id} if range_id else {}
        try:
            data = await self._req("GET", "/range", params=params)
        except LudusError as e:
            if "404" in str(e):
                return RangeStatus(state=RangeState.ABSENT)
            raise
        vms: list[VMHandle] = []
        state = RangeState.ABSENT
        rid = range_id
        if isinstance(data, dict):
            state_s = (data.get("status") or data.get("state") or "").lower()
            if "deploy" in state_s or "build" in state_s:
                state = RangeState.DEPLOYING
            elif data.get("vms") or state_s in ("running", "deployed", "success"):
                state = RangeState.RUNNING
            for v in data.get("vms", []) or []:
                vms.append(
                    VMHandle(
                        name=v.get("name") or v.get("hostname") or "",
                        vmid=v.get("vmid") or v.get("vm_id"),
                        ip=v.get("ip") or v.get("ip_address"),
                        template=v.get("template"),
                    )
                )
            rid = data.get("rangeID") or data.get("range_id") or range_id
        log_tail = ""
        if state in (RangeState.DEPLOYING, RangeState.FAILED):
            try:
                tail = await self.deploy_logs(range_id)
                log_tail = tail[-8000:]  # cap: ansible logs can be huge
            except Exception:
                pass
        return RangeStatus(state=state, vms=vms, range_id=rid, log_tail=log_tail)

    async def deploy_logs(self, range_id: str | None = None) -> str:
        params = {"rangeID": range_id} if range_id else {}
        data = await self._try("GET", "/range/logs", "/range/deploy/logs", params=params)
        return data if isinstance(data, str) else str(data)

    async def destroy_range(self, range_id: str | None = None) -> None:
        params = {"rangeID": range_id} if range_id else {}
        await self._req("DELETE", "/range", params=params)

    async def snapshot_all(self, range_id: str | None, snap_name: str = SNAP_POST_DEPLOY) -> None:
        # Ludus exposes VM snapshots; implementation varies → do it via engine PVE.
        st = await self.status(range_id)
        for vm in st.vms:
            if vm.vmid:
                try:
                    upid = await self.pve.snapshot_create(vm.vmid, snap_name)
                    await self.pve.wait_task(upid, timeout_s=600)
                except Exception as e:  # existing snap / offline vm — continue best-effort
                    await log.awarning("snapshot failed", vmid=vm.vmid, error=str(e))

    async def rollback_all(self, range_id: str | None, snap_name: str = SNAP_POST_DEPLOY) -> None:
        st = await self.status(range_id)
        for vm in st.vms:
            if vm.vmid:
                try:
                    upid = await self.pve.snapshot_rollback(vm.vmid, snap_name)
                    await self.pve.wait_task(upid, timeout_s=300)
                except Exception as e:
                    await log.awarning("rollback failed", vmid=vm.vmid, error=str(e))

    async def testing_mode(self, enable: bool, allow_ips: list[str] | None = None) -> None:
        body: dict[str, Any] = {"enabled": enable}
        if allow_ips:
            body["allow"] = allow_ips
            body["allowed_ips"] = allow_ips
        try:
            await self._try("POST", "/testing", "/range/testing", json=body)
        except LudusError as e:
            await log.awarning("testing-mode endpoint unavailable", error=str(e))

    async def ensure_role(self, role_name: str, *, url: str | None = None, directory: str | None = None) -> None:
        try:
            await self._req(
                "POST",
                "/ansible/role",
                json={"role": url or directory or role_name, "action": "install", "global": True},
            )
        except LudusError as e:
            await log.awarning("role install failed", role=role_name, error=str(e))

    async def ansible_inventory(self, range_id: str | None = None) -> str:
        params = {"rangeID": range_id} if range_id else {}
        data = await self._try("GET", "/range/ansibleinventory", "/range/inventory", params=params)
        return data if isinstance(data, str) else str(data)

    async def health(self) -> dict:
        try:
            ver = await self._try("GET", "/version", "/health", "/")
            pve_ver = await self.pve.version()
            return {"ok": True, "ludus": ver, "pve": pve_ver.get("version") if isinstance(pve_ver, dict) else pve_ver}
        except Exception as e:
            return {"ok": False, "error": str(e)}
