"""LudusProvider: RangeProvider over the Ludus 2 REST API (https://ludus.cloud).

Ludus 2 serves its API under /api/v2 on :8080 with X-API-KEY auth. The range
config is a YAML file uploaded multipart (field `file`) — it is NOT a JSON
body. Where Ludus has no endpoint (e.g. snapshot rollback), we delegate to
the engine-PVE client — the engine is ours anyway.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import httpx
import structlog
import yaml

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
        base = base_url.rstrip("/")
        # Ludus 2 mounts the api at /api/v2; tolerate urls that already carry it
        self._base = base if base.endswith("/api/v2") else base + "/api/v2"
        self._client = httpx.AsyncClient(
            headers={"X-API-KEY": api_key},
            verify=verify_tls,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    async def close(self) -> None:
        await self._client.aclose()
        await self.pve.close()

    async def _req(self, method: str, path: str, **kw) -> Any:
        r = await self._client.request(method, self._base + path, **kw)
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
        # a previous deploy may have left testing mode on — while it is, Ludus
        # refuses ANY new range config with 409. Stop it first; harmless when off.
        with suppress(LudusError):
            await self._req("PUT", "/testing/stop")
        # range config is a YAML file upload, multipart field name "file"
        payload = yaml.safe_dump(config, sort_keys=False).encode()
        try:
            await self._req(
                "PUT", "/range/config",
                files={"file": ("range-config.yml", payload, "application/x-yaml")},
            )
        except LudusError as e:
            # destroy_range deletes the range OBJECT in Ludus 2 — PUT config on a
            # missing default range 404s. Recreate the range, then retry once.
            if "404" not in str(e):
                raise
            await self._create_range(name)
            await self._req(
                "PUT", "/range/config",
                files={"file": ("range-config.yml", payload, "application/x-yaml")},
            )
        await self._req("POST", "/range/deploy", json={})
        st = await self.status()
        # Never return `name` — it isn't a ludus rangeID and would poison later
        # status(rangeID=...) filters. "" → subsequent calls use the default range.
        return st.range_id or ""

    async def _create_range(self, name: str) -> None:
        """POST /api/v2/ranges/create — the first/only range becomes the user's
        default automatically. rangeID must be a valid proxmox pool name; the
        ludus API key is `<userID>.<secret>` so the user is derivable."""
        user = self._api_key.split(".", 1)[0]
        body: dict[str, Any] = {"rangeID": name, "name": name}
        if user:
            body["userID"] = [user]
        try:
            await self._req("POST", "/ranges/create", json=body)
        except LudusError as e:
            # 409 "already in use" → a range exists; PUT config will land on the
            # default range — nothing to do.
            if "409" not in str(e):
                raise

    async def status(self, range_id: str | None = None) -> RangeStatus:
        params = {"userID": range_id} if range_id else {}
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
            # ludus 2: {"rangeState": "NEVER DEPLOYED"|"DEPLOYING"|"DEPLOYED"|"ERROR", "VMs": [...]}
            state_s = str(data.get("rangeState") or data.get("status") or data.get("state") or "").lower()
            if "deploying" in state_s or "building" in state_s:
                state = RangeState.DEPLOYING
            elif "deployed" in state_s or "running" in state_s or "success" in state_s:
                state = RangeState.RUNNING
            elif "error" in state_s or "fail" in state_s:
                state = RangeState.FAILED
            elif data.get("VMs") or data.get("vms"):
                state = RangeState.RUNNING
            for v in data.get("VMs") or data.get("vms") or []:
                name = v.get("name") or v.get("hostname") or v.get("vmName") or ""
                vms.append(
                    VMHandle(
                        name=name,
                        # ludus 2 exposes the hypervisor id as proxmoxID
                        vmid=v.get("vmid") or v.get("vmID") or v.get("vm_id")
                             or v.get("proxmoxID"),
                        ip=v.get("ip") or v.get("ipAddress") or v.get("ip_address"),
                        template=v.get("template"),
                        role=("router" if v.get("isRouter")
                              else "kali" if "kali" in name.lower() else "target"),
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
        params = {"userID": range_id} if range_id else {}
        data = await self._try("GET", "/range/logs", "/range/deploy/logs", params=params)
        return data if isinstance(data, str) else str(data)

    async def destroy_range(self, range_id: str | None = None) -> None:
        # don't leave the wire shut behind a deleted range
        with suppress(LudusError):
            await self._req("PUT", "/testing/stop")
        params = {"force": "true"}
        if range_id:
            params["userID"] = range_id
        # Ludus 2 refuses DELETE /range while VMs exist (409 "use --force") —
        # and even force 500s on a VM that's still running or mid-task:
        # destroy the VMs explicitly first, then the range, one retry for
        # stragglers whose delete raced a still-closing task.
        with suppress(LudusError):
            await self._req("DELETE", "/range/vms", params=params)
            await asyncio.sleep(5)
        try:
            await self._req("DELETE", "/range", params=params)
        except LudusError:
            await asyncio.sleep(10)
            await self._try("DELETE", "/range", params=params)

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
        # ludus 2: PUT /testing/start|stop; allowed ips via POST /testing/allow
        # with body {"allowed": [ip, ...]} — {"ip": ...} is silently ignored
        try:
            await self._req("PUT", "/testing/start" if enable else "/testing/stop")
            if enable and allow_ips:
                await self._req("POST", "/testing/allow", json={"allowed": allow_ips})
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
        params = {"userID": range_id} if range_id else {}
        data = await self._try("GET", "/range/ansibleinventory", "/range/inventory", params=params)
        return data if isinstance(data, str) else str(data)

    async def health(self) -> dict:
        try:
            ver = await self._req("GET", "/")           # → {"version": "2.3.10+…"}
            pve_ver = await self.pve.version()
            return {"ok": True, "ludus": ver, "pve": pve_ver.get("version") if isinstance(pve_ver, dict) else pve_ver}
        except Exception as e:
            return {"ok": False, "error": str(e)}
