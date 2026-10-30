"""RangeProvider: abstraction over the range engine (Ludus / mock / future proxmox-direct)."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Protocol


class RangeState(str, enum.Enum):
    ABSENT = "absent"
    DEPLOYING = "deploying"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class VMHandle:
    name: str
    vmid: int | None = None
    ip: str | None = None
    template: str | None = None
    role: str = "target"  # kali|target


@dataclass
class RangeStatus:
    state: RangeState
    vms: list[VMHandle] = field(default_factory=list)
    range_id: str | None = None
    log_tail: str = ""


class RangeProvider(Protocol):
    """What the session service needs from a range engine."""

    async def deploy_range(self, name: str, config: dict, *, force: bool = False) -> str:
        """Create+deploy a range. Returns range_id. Long-running: poll status()."""
        ...

    async def status(self, range_id: str | None = None) -> RangeStatus: ...

    async def deploy_logs(self, range_id: str | None = None) -> str: ...

    async def destroy_range(self, range_id: str | None = None) -> None: ...

    async def snapshot_all(self, range_id: str | None, snap_name: str) -> None:
        """Snapshot every VM in the range (post-deploy restore point)."""
        ...

    async def rollback_all(self, range_id: str | None, snap_name: str) -> None:
        """Soft-reset: revert every VM in the range to the snapshot."""
        ...

    async def testing_mode(self, enable: bool, allow_ips: list[str] | None = None) -> None:
        """Internet isolation for the range (allowlist for telemetry egress)."""
        ...

    async def ensure_role(self, role_name: str, *, url: str | None = None, directory: str | None = None) -> None:
        """Make sure an ansible role exists on the engine (install from galaxy/url/dir)."""
        ...

    async def health(self) -> dict: ...
