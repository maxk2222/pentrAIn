"""MockProvider: full range lifecycle simulation for development & CI (no hypervisor).

Simulates deploy delays, returns deterministic fake VMIDs, fabricates snapshots
and lets tests drive the whole session lifecycle. Also emits fake telemetry so
the coach/UI can be developed end-to-end on a laptop.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

from .base import RangeState, RangeStatus, VMHandle


@dataclass
class _Range:
    range_id: str
    config: dict
    state: RangeState = RangeState.DEPLOYING
    deploy_start: float = 0.0
    deploy_ticks: int = 0
    vms: list[VMHandle] = field(default_factory=list)
    snapshots: set[str] = field(default_factory=set)
    logs: list[str] = field(default_factory=list)


class MockProvider:
    TICK_S = 0.2

    def __init__(self, *, deploy_ticks: int = 4):
        self._ranges: dict[str, _Range] = {}
        self._ids = itertools.count(100)
        self._deploy_ticks = deploy_ticks
        self.guest_exec_log: list[tuple[int, list[str]]] = []

    async def deploy_range(self, name: str, config: dict, *, force: bool = False) -> str:
        rid = "MO"
        # accept both ludus format {"ludus": [...]} and flat {"vms": [...], "kali": {...}}
        vmdefs = config.get("ludus") or config.get("vms") or []
        vms: list[VMHandle] = []
        for i, vmdef in enumerate(vmdefs):
            vms.append(
                VMHandle(
                    name=vmdef.get("vm_name") or vmdef.get("name") or f"vm{i}",
                    vmid=next(self._ids),
                    ip=f"10.101.{vmdef.get('vlan', 10)}.{vmdef.get('ip_last_octet', 10 + i)}",
                    template=vmdef.get("template"),
                    role=vmdef.get("role", "target"),
                )
            )
        if not any(v.role == "kali" for v in vms):
            vms.insert(
                0,
                VMHandle(name="kali", vmid=next(self._ids), ip="10.101.10.5",
                         template=config.get("kali", {}).get("template", "kali-x64-desktop-template"),
                         role="kali"),
            )
        r = _Range(range_id=rid, config=config, vms=vms, deploy_start=time.monotonic())
        r.logs.append(f"[mock] deploying range {rid} ({len(vms)} VMs)")
        self._ranges[rid] = r
        return rid

    def _tick(self, r: _Range) -> None:
        """Deterministic deploy progress — driven by status() polls, no timers
        (call_later callbacks don't fire reliably under uvicorn's uvloop)."""
        if r.state != RangeState.DEPLOYING:
            return
        ticks = min(self._deploy_ticks, int((time.monotonic() - r.deploy_start) / self.TICK_S) + 1)
        while r.deploy_ticks < ticks:
            r.deploy_ticks += 1
            r.logs.append(f"[mock] deploy tick {r.deploy_ticks}/{self._deploy_ticks}")
        if r.deploy_ticks >= self._deploy_ticks:
            r.state = RangeState.RUNNING
            r.logs.append("[mock] range RUNNING")

    async def status(self, range_id: str | None = None) -> RangeStatus:
        r = self._ranges.get(range_id or "MO")
        if not r:
            return RangeStatus(state=RangeState.ABSENT)
        self._tick(r)
        return RangeStatus(state=r.state, vms=list(r.vms), range_id=r.range_id,
                           log_tail="\n".join(r.logs[-20:]))

    async def deploy_logs(self, range_id: str | None = None) -> str:
        r = self._ranges.get(range_id or "MO")
        return "\n".join(r.logs) if r else ""

    async def destroy_range(self, range_id: str | None = None) -> None:
        self._ranges.pop(range_id or "MO", None)

    async def snapshot_all(self, range_id: str | None, snap_name: str) -> None:
        r = self._ranges.get(range_id or "MO")
        if r:
            r.snapshots.add(snap_name)
            r.logs.append(f"[mock] snapshot_all {snap_name}")

    async def rollback_all(self, range_id: str | None, snap_name: str) -> None:
        r = self._ranges.get(range_id or "MO")
        if r:
            if snap_name not in r.snapshots:
                raise RuntimeError(f"mock: snapshot {snap_name} not found")
            r.logs.append(f"[mock] rollback_all {snap_name}")

    async def testing_mode(self, enable: bool, allow_ips: list[str] | None = None) -> None:
        pass

    async def ensure_role(self, role_name: str, *, url: str | None = None, directory: str | None = None) -> None:
        pass

    async def health(self) -> dict:
        return {"ok": True, "provider": "mock", "ranges": len(self._ranges)}


class MockPveClient:
    """Drop-in replacement for PveClient in mock/dev mode."""

    def __init__(self):
        self.exec_log: list[tuple[int, list[str]]] = []
        self.files: dict[tuple[int, str], bytes] = {}

    async def close(self) -> None: ...

    async def version(self) -> dict:
        return {"version": "mock-pve-9.0"}

    async def node_status(self) -> dict:
        return {"cpu": 0.05, "memory": {"used": 4 << 20, "total": 96 << 30}}

    async def vncproxy(self, vmid: int) -> dict:
        return {"ticket": "MOCKVNC", "port": "5900", "password": "mock"}

    def vnc_websocket_url(self, vmid: int, port: str, vncticket: str) -> str:
        return "mock://console"

    def ssl_context(self):
        import ssl
        return ssl.create_default_context()

    async def agent_exec(self, vmid: int, argv: list[str], *, timeout_s: int = 120) -> dict:
        self.exec_log.append((vmid, argv))
        cmd = argv[-1] if argv else ""
        if "base64 -d >" in cmd:  # file write via agent_write_file
            return {"out": "", "err": "", "exitcode": 0}
        if "has-session" in cmd:  # no desktop tmux in mock mode → direct exec path
            return {"out": "", "err": "no server running", "exitcode": 1}
        return {"out": f"[mock] executed: {' '.join(argv)}\n", "err": "", "exitcode": 0}

    async def agent_exec_sh(self, vmid: int, shell_cmd: str, *, timeout_s: int = 120) -> dict:
        return await self.agent_exec(vmid, ["/bin/sh", "-c", shell_cmd], timeout_s=timeout_s)

    async def agent_write_file(self, vmid: int, path: str, content: str | bytes) -> None:
        self.files[(vmid, path)] = content.encode() if isinstance(content, str) else content

    async def agent_file_read(self, vmid: int, path: str) -> bytes:
        return self.files.get((vmid, path), b"[mock] empty\n")

    async def snapshot_create(self, vmid: int, name: str, description: str = "pentrain") -> str:
        return f"UPID:mock:snap:{vmid}:{name}"

    async def snapshot_rollback(self, vmid: int, name: str) -> str:
        return f"UPID:mock:rollback:{vmid}:{name}"

    async def vm_start(self, vmid: int) -> str:
        return "UPID:mock:start"

    async def vm_stop(self, vmid: int) -> str:
        return "UPID:mock:stop"

    async def task_status(self, upid: str) -> dict:
        return {"status": "stopped", "exitstatus": "OK"}

    async def wait_task(self, upid: str, timeout_s: int = 300) -> dict:
        return {"status": "stopped", "exitstatus": "OK"}
