"""Proxmox VE API client for the *engine* hypervisor.

Used for: vncproxy/vncwebsocket (console), qemu-guest-agent exec (coach takeover,
flag injection, telemetry config), snapshots (soft reset), resource status.
"""
from __future__ import annotations

import asyncio
import base64
import ssl
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class PveCreds:
    base_url: str            # https://host:8006
    token_id: str            # user@realm!tokenid
    token_secret: str
    verify_tls: bool = False
    node: str = "pve"


class PveError(RuntimeError):
    pass


def _b64(raw: Any) -> str:
    """Decode a base64 guest-agent field; '' on absent/undecodable input."""
    if not isinstance(raw, str) or not raw:
        return ""
    try:
        return base64.b64decode(raw, validate=True).decode("utf-8", "replace")
    except Exception:
        return ""


class PveClient:
    def __init__(self, creds: PveCreds):
        self.creds = creds
        self._client = httpx.AsyncClient(
            base_url=creds.base_url.rstrip("/") + "/api2/json",
            headers={"Authorization": f"PVEAPIToken={creds.token_id}={creds.token_secret}"},
            verify=creds.verify_tls,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _req(self, method: str, path: str, **kw) -> Any:
        r = await self._client.request(method, path, **kw)
        if r.status_code >= 400:
            raise PveError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        data = r.json()
        return data.get("data")

    async def get(self, path: str, **kw) -> Any:
        return await self._req("GET", path, **kw)

    async def post(self, path: str, **kw) -> Any:
        return await self._req("POST", path, **kw)

    async def put(self, path: str, **kw) -> Any:
        return await self._req("PUT", path, **kw)

    # ---------- status ----------
    async def version(self) -> dict:
        return await self.get("/version")

    async def node_status(self) -> dict:
        return await self.get(f"/nodes/{self.creds.node}/status")

    async def vm_status(self, vmid: int) -> dict:
        return await self.get(f"/nodes/{self.creds.node}/qemu/{vmid}/status/current")

    async def node_rrddata(self, timeframe: str = "hour") -> list[dict]:
        data = await self.get(f"/nodes/{self.creds.node}/rrddata",
                              params={"timeframe": timeframe})
        return data if isinstance(data, list) else []

    async def vm_rrddata(self, vmid: int, timeframe: str = "hour") -> list[dict]:
        data = await self.get(f"/nodes/{self.creds.node}/qemu/{vmid}/rrddata",
                              params={"timeframe": timeframe})
        return data if isinstance(data, list) else []

    # ---------- console ----------
    async def vncproxy(self, vmid: int) -> dict:
        """Returns {'ticket': vnc_ticket, 'port': port}. Connect via vncwebsocket."""
        return await self.post(
            f"/nodes/{self.creds.node}/qemu/{vmid}/vncproxy",
            data={"websocket": "1", "generate-password": "1"},
        )

    def vnc_websocket_url(self, vmid: int, port: str, vncticket: str) -> str:
        host = self.creds.base_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
        q = urllib.parse.urlencode({"port": port, "vncticket": vncticket})
        return f"{host}/api2/json/nodes/{self.creds.node}/qemu/{vmid}/vncwebsocket?{q}"

    def ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        if not self.creds.verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    # ---------- guest agent ----------
    async def agent_exec(self, vmid: int, argv: list[str], *, timeout_s: int = 120) -> dict:
        """Run argv in guest via qemu-guest-agent. Returns {'out':..., 'err':..., 'exitcode':...}."""
        data = await self.post(
            f"/nodes/{self.creds.node}/qemu/{vmid}/agent/exec",
            json={"command": argv},
        )
        pid = data.get("pid") if isinstance(data, dict) else None
        if pid is None:
            raise PveError(f"agent/exec returned no pid: {data}")
        for _ in range(timeout_s * 2):
            st = await self.get(
                f"/nodes/{self.creds.node}/qemu/{vmid}/agent/exec-status",
                params={"pid": pid},
            )
            if st and st.get("exited"):
                # qemu-guest-agent contract: out-data/err-data are ALWAYS base64
                out = _b64(st.get("out-data")) or str(st.get("out") or "")
                err = _b64(st.get("err-data")) or str(st.get("err") or "")
                return {"out": out, "err": err, "exitcode": st.get("exitcode", 0)}
            await asyncio.sleep(0.5)
        raise PveError(f"agent/exec timed out after {timeout_s}s (vmid={vmid})")

    async def agent_exec_sh(self, vmid: int, shell_cmd: str, *, timeout_s: int = 120) -> dict:
        return await self.agent_exec(vmid, ["/bin/sh", "-c", shell_cmd], timeout_s=timeout_s)

    async def agent_write_file(self, vmid: int, path: str, content: str | bytes) -> None:
        b64 = base64.b64encode(content.encode() if isinstance(content, str) else content).decode()
        await self.agent_exec_sh(
            vmid, f"mkdir -p $(dirname {path}) && echo {b64} | base64 -d > {path}"
        )

    async def agent_file_read(self, vmid: int, path: str) -> bytes:
        data = await self.get(
            f"/nodes/{self.creds.node}/qemu/{vmid}/agent/file-read",
            params={"file": path},
        )
        raw = data.get("content", "") if isinstance(data, dict) else ""
        return base64.b64decode(raw)

    # ---------- snapshots / power ----------
    async def snapshot_create(self, vmid: int, name: str, description: str = "pentrain") -> str:
        return await self.post(
            f"/nodes/{self.creds.node}/qemu/{vmid}/snapshot",
            data={"snapname": name, "description": description},
        )

    async def snapshot_rollback(self, vmid: int, name: str) -> str:
        return await self.post(
            f"/nodes/{self.creds.node}/qemu/{vmid}/snapshot/{name}/rollback"
        )

    async def vm_start(self, vmid: int) -> str:
        return await self.post(f"/nodes/{self.creds.node}/qemu/{vmid}/status/start")

    async def vm_stop(self, vmid: int) -> str:
        return await self.post(f"/nodes/{self.creds.node}/qemu/{vmid}/status/stop")

    # ---------- tasks ----------
    async def task_status(self, upid: str) -> dict:
        node = upid.split(":")[1] if ":" in upid else self.creds.node
        return await self.get(f"/nodes/{node}/tasks/{upid}/status")

    async def wait_task(self, upid: str, timeout_s: int = 300) -> dict:
        for _ in range(timeout_s * 2):
            st = await self.task_status(upid)
            if st.get("status") == "stopped":
                exitstatus = st.get("exitstatus", "OK")
                if exitstatus != "OK":
                    raise PveError(f"task {upid} failed: {exitstatus}")
                return st
            await asyncio.sleep(0.5)
        raise PveError(f"task {upid} timed out")
