"""Typed settings registry — every user-facing config lives in DB, editable via WebGUI."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.domain import Setting

# key -> (default, secret?)
DEFAULTS: dict[str, tuple[Any, bool]] = {
    "engine.mode": ("nested", False),              # nested|direct|mock
    "engine.pve_url": ("", False),
    "engine.pve_node": ("pve", False),
    "engine.pve_token_id": ("", False),
    "engine.pve_token_secret": ("", True),
    "engine.ludus_url": ("", False),
    "engine.ludus_api_key": ("", True),
    "engine.hoststats_url": ("", False),            # optional pentrain-hoststats agent; empty → derive from pve_url :9100
    "engine.testing_mode": (True, False),           # cut range internet after deploy
    "engine.testing_allow": ([], False),            # CIDRs allowed while testing (app VM)
    "engine.kali_template": ("", False),            # custom kali template name — empty = per-quest default
    "engine.kali_wan_bridge": ("vmbr0", False),     # bridge with real internet for kali net1 + builder VM
    "kali.internet_default": (False, False),        # attach kali WAN nic on new sessions
    "lan.scope_cidr": ("", False),                  # authorized LAN scope for home-lab mode; empty = auto-detect /24 from WAN lease
    "kali.builder_vmid": (0, False),                # internal: in-flight template-builder VM
    "platform.api_url": ("http://pentrain-app:8000", False),  # backend URL reachable from ranges
    "resources.gate_mode": ("live", False),      # live|static|off — how quest
                                               # unlock weighs host capacity
    "resources.ram_headroom": (0.85, False),     # floor must fit under
                                               # free_ram × this fraction
    "resources.vcpu_overcommit": (4.0, False),   # vcpus vs host cores factor
    "resources.max_ram_gb": (48, False),
    "resources.max_vcpus": (16, False),
    "resources.max_disk_gb": (500, False),
    "llm.base_url": ("http://localhost:11434/v1", False),
    "llm.api_key": ("", True),
    "llm.model": ("huihui-ai/Qwen3-30B-A3B-abliterated", False),
    "llm.vision_model": ("", False),
    "llm.temperature": (0.4, False),
    "llm.daily_token_budget": (10_000_000, False),
    "llm.reasoning": (True, False),               # let thinking models reason before answering
    "llm.reasoning_effort": ("medium", False),    # low|medium|high (reasoning_effort field)
    "coach.default_autonomy": (2, False),
    "coach.verbosity": ("normal", False),          # terse|normal|verbose
    "coach.personality": ("mentor", False),
    "coach.enabled": (True, False),
    "coach.reflect_interval_s": (60, False),
    "coach.nudge_after_s": (480, False),
    "coach.hint_after_s": (900, False),
    "coach.action_budget": (400, False),
    "coach.action_grace": (80, False),           # soft-cap window after budget
    "coach.takeover_pace_s": (10, False),        # min gap between L4 chains
    "coach.takeover_chain_max": (48, False),     # max LLM calls per L4 turn
    "coach.max_workers": (8, False),             # parallel L4 subagent panes
    "coach.worker_turn_cap": (80, False),        # LLM turns per worker task
    "coach.worker_time_cap_s": (3600, False),    # wall-clock per worker task
    "coach.collect_wait_s": (240, False),        # collect_agent block bound
    "coach.wait_max_s": (600, False),            # cap per wait-tool call
    "coach.observer_enabled": (True, False),     # session observer learns+advises
    "coach.observer_tick_s": (60, False),        # poll interval for traj tails
    "coach.observer_stuck_s": (600, False),      # no-progress window = stuck
    "coach.observer_min_denials": (2, False),    # denial floor for stuck detect
    "coach.observer_max_proposals": (2, False),  # lessons per analysis call
    "coach.observer_max_lessons_session": (4, False),
    "coach.observer_cooldown_s": (900, False),   # min gap between analyses/session
    "coach.observer_hint_min_level": (3, False), # hints need an autonomous loop
    "content.packs": (["bundled"], False),
    "data.telemetry_retention_days": (30, False),
    "security.admin_token_hash": ("", True),
    "setup.completed": (False, False),
}


async def get_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    row = await db.get(Setting, key)
    if row is not None:
        return row.value.get("v")
    if key in DEFAULTS:
        return DEFAULTS[key][0]
    return default


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    row = await db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value={"v": value})
        db.add(row)
    else:
        row.value = {"v": value}
    await db.commit()


async def all_settings(db: AsyncSession, *, redact: bool = True) -> dict[str, Any]:
    rows = (await db.execute(select(Setting))).scalars().all()
    stored = {r.key: r.value.get("v") for r in rows}
    out: dict[str, Any] = {}
    for key, (default, secret) in DEFAULTS.items():
        v = stored.get(key, default)
        out[key] = "********" if (secret and v and redact) else v
    for key, v in stored.items():  # unknown custom keys pass through
        out.setdefault(key, v)
    return out


def _coerce(key: str, value: Any) -> Any:
    """Coerce a PATCHed value to the registered default's type.

    Without this a UI bug could store "abc" into resources.max_ram_gb and
    crash every int() consumer downstream. Raises ValueError on mismatch.
    """
    default = DEFAULTS[key][0]
    if value is None:
        return default
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(value, (int, float)):
            return bool(value)
        raise ValueError(f"{key}: expected bool")
    if isinstance(default, int):  # after bool — bool is an int subclass
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key}: expected int") from None
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key}: expected number") from None
    if isinstance(default, list):
        if not isinstance(value, list):
            raise ValueError(f"{key}: expected list")
        return value
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError(f"{key}: expected string")
        return value
    return value


async def patch_settings(db: AsyncSession, updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if value == "********":  # redacted echo — keep stored secret
            continue
        if key in DEFAULTS:
            value = _coerce(key, value)
        await set_setting(db, key, value)


async def get_secret(db: AsyncSession, key: str) -> str:
    """Unredacted read for server-side use."""
    row = await db.get(Setting, key)
    return (row.value.get("v") if row else DEFAULTS.get(key, ("",))[0]) or ""
