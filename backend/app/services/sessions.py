"""Session lifecycle: QUEUED → DEPLOYING → READY → ACTIVE → SOLVED|ABORTED|FAILED
                                                      ↘ RESETTING → READY

One active session at a time (v1). Deploy/reset run as background asyncio tasks;
every transition persists to DB and broadcasts on the event bus so UI + coach
survive restarts and stay in sync.
"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
from datetime import UTC, datetime
from urllib.parse import urlparse

import structlog
import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import session_factory
from ..models.domain import (
    AssistUse,
    Attempt,
    CoachAction,
    CoachMessage,
    CoachSessionState,
    Flag,
    FlagSubmission,
    HintUse,
    Quest,
    QuestCheckpoint,
    Session,
    SessionState,
    TelemetryEvent,
)
from ..ranges.base import RangeState
from ..ranges.ludus import SNAP_POST_DEPLOY
from . import coach_bridge
from . import flags as flags_svc
from . import kali_net as kali_net_svc
from . import scoring as scoring_svc
from . import settings as settings_svc
from .engine import get_engine
from .events import bus, ephemeral_clear, publish_session
from .flags import new_seed, new_telemetry_token

# pentest/tooling binaries the coach's KALI_TOOLS context reports on —
# the inventory is probed live post-deploy, so template drift shows up
# as facts instead of "command not found" surprises
KALI_TOOL_PROBE = [
    "nmap", "masscan", "netdiscover", "arp-scan",
    "gobuster", "feroxbuster", "dirb", "ffuf", "nikto", "wpscan", "sqlmap",
    "hydra", "john", "hashcat", "medusa",
    "smbclient", "enum4linux-ng", "nbtscan", "rpcclient", "ldapsearch",
    "ftp", "nc", "ncat", "socat", "telnet", "tftp", "atftp",
    "dig", "snmpwalk", "whois",
    "ssh", "sshpass", "expect", "sshuttle", "chisel", "proxychains4",
    "mysql", "mariadb", "psql", "redis-cli", "sqlite3",
    "rdesktop", "xfreerdp3", "evil-winrm",
    "curl", "wget", "jq", "python3", "msfconsole", "git",
    "searchsploit",
    "tcpdump", "tshark", "aircrack-ng", "iw",
]

log = structlog.get_logger(__name__)

_tasks: dict[int, asyncio.Task] = {}
_create_lock = asyncio.Lock()  # serializes active-check + insert
POLL_S = 10          # status poll interval during deploy (patched in tests)


def _own(sid: int) -> bool:
    """True while the running task is the tracked lifecycle task for sid.

    reset/resume/abort paths displace each other by overwriting _tasks[sid];
    the displaced coroutine must not keep mutating session state (s42: a
    restart-resume _deploy raced a verify-triggered hard reset — the loser's
    _finalize committed kali_vmid=None over the winner's). Lifecycle tasks
    check this at stage boundaries; callers must only pop _tasks[sid] when
    they still own it."""
    return _tasks.get(sid) is asyncio.current_task()


def _claim(sid: int) -> None:
    """Mark the running task as sid's lifecycle owner — for tests and inline
    callers that invoke _deploy/_reset/_resume directly instead of going
    through the public spawn paths (which register _tasks[sid] themselves)."""
    _tasks[sid] = asyncio.current_task()


class SessionError(RuntimeError):
    pass


class _Displaced(Exception):
    """Internal — a lifecycle task hit an ownership checkpoint after a newer
    task displaced it. Must NOT mark the session failed: the new owner is
    managing state now."""


# ---------------- helpers ----------------

async def _broadcast(session_id: int, type_: str, data: dict | None = None) -> None:
    await bus.publish(f"session.{session_id}", {
        "type": type_, "session_id": session_id, "data": data or {}})


async def _broadcast_solved(session_id: int, attempt: Attempt) -> None:
    await _broadcast(session_id, "solved", {
        "score": attempt.score, "attempt_id": attempt.id,
        "duration_s": attempt.duration_s, "runs": attempt.runs or 1,
        "breakdown": attempt.breakdown or {}})


async def _set_state(db: AsyncSession, session: Session, state: SessionState,
                     **fields) -> None:
    session.state = state.value
    for k, v in fields.items():
        setattr(session, k, v)
    await db.commit()
    await _broadcast(session.id, "state", {"state": state.value, **{k: str(v) for k, v in fields.items() if v is not None}})
    if state in (SessionState.ABORTED, SessionState.FAILED,
                 SessionState.SOLVED, SessionState.RESETTING):
        # terminal (or wiping for a fresh run) — no replayed drafts/activity
        # should outlive the session
        ephemeral_clear(session.id)


async def _append_log(db: AsyncSession, session: Session, line: str) -> None:
    session.deploy_log = (session.deploy_log or "") + line + "\n"
    await db.commit()
    await _broadcast(session.id, "deploy_log", {"line": line})


async def _append_log_by_id(db: AsyncSession, session_id: int, line: str) -> None:
    """Log-append for contexts where the Session ORM object may be expired —
    loads + commits in the same tx."""
    session = await db.get(Session, session_id)
    if session:
        await _append_log(db, session, line)


def _api_ip_port(api_url: str | None) -> tuple[str | None, int]:
    """platform.api_url → (ipv4 host | None, port). Only IPv4 literals can be
    turned into Ludus network rules — hostnames don't resolve inside ranges."""
    if not api_url:
        return None, 8000
    try:
        u = urlparse(api_url if "://" in api_url else f"http://{api_url}")
        host = u.hostname or ""
        ipaddress.IPv4Address(host)
        return host, u.port or (443 if u.scheme == "https" else 80)
    except ValueError:
        return None, 8000


def _merge_testing_allow(allow: list, api_ip: str | None) -> list:
    """User-configured testing allow list + the platform API's /32 — the
    range must reach telemetry/terminal even while testing-mode isolates
    the rest of the WAN."""
    if api_ip and f"{api_ip}/32" not in allow:
        return [*allow, f"{api_ip}/32"]
    return allow


def compile_topology(quest: Quest, kali_template: str | None = None) -> dict:
    """quest.topology → Ludus range config (subset of Ludus schema we need).

    `kali_template` (engine.kali_template setting) overrides the per-quest
    template globally — a user's custom build is meant to apply everywhere.

    Every VM carries ram_min_gb alongside ram_gb — Ludus maps it to Proxmox
    memory ballooning, so a range squeezed onto a small host still boots and
    shrinks under pressure instead of being refused outright.
    """
    topo = quest.topology or {}
    vms: list[dict] = []
    kali = topo.get("kali") or {}
    # the kali worker is platform infrastructure, not quest content — a
    # starved spec boots too slowly for the deploy-time QGA lookup
    kali_ram = max(4, int(kali.get("ram_gb", 6) or 6))
    kali_cpus = max(2, int(kali.get("cpus", 4) or 4))
    vms.append({
        "vm_name": "{{ range_id }}-kali",
        "hostname": "{{ range_id }}-KALI",
        "template": kali_template or kali.get("template", "kali-x64-desktop-template"),
        "vlan": 10,
        "ip_last_octet": 5,
        "ram_gb": kali_ram,
        "ram_min_gb": min(kali_ram - 1, int(kali.get("ram_min_gb")
                          or kali_ram // 2)),
        "cpus": kali_cpus,
        "linux": True,
        "roles": ["pentrain_kali_agent", "pentrain_research_kit",
                  *(kali.get("roles") or [])],
    })
    for i, v in enumerate(topo.get("vms") or []):
        ram_gb = v.get("ram_gb", 4)
        entry = {
            "vm_name": f"{{{{ range_id }}}}-{v['name']}",
            "hostname": f"{{{{ range_id }}}}-{v['name'].upper()[:14]}",
            "template": v["template"],
            "vlan": v.get("vlan", 10),
            "ip_last_octet": v.get("ip_last_octet") or 20 + i,
            "ram_gb": ram_gb,
            "ram_min_gb": v.get("ram_min_gb") or max(1, ram_gb // 2),
            "cpus": v.get("cpus", 2),
            "linux": v.get("linux", True),
        }
        if v.get("windows"):
            entry["windows"] = dict(v["windows"])
            entry["linux"] = False
        if v.get("domain"):
            entry["domain"] = v["domain"]
        if v.get("gpos"):
            # Ludus expects gpos under windows.gpos — VmSpec keeps them
            # top-level for yaml ergonomics
            entry.setdefault("windows", {})["gpos"] = v["gpos"]
            entry["linux"] = False
        roles = list(v.get("roles") or [])
        if entry["linux"]:
            # lightweight telemetry on every linux target — commands typed
            # inside an SSH session on the target must reach the checkpoint
            # matcher/coach just like kali-side commands do
            names = [r if isinstance(r, str) else r.get("name") for r in roles]
            if "pentrain_target_agent" not in names and "pentrain_kali_agent" not in names:
                roles.insert(0, "pentrain_target_agent")
        if roles:
            entry["roles"] = roles
        vms.append(entry)
    # Ludus auto-adds the router VM (default debian-13 template, 2G). We pin
    # debian-12 — the server template every linux quest already requires —
    # and size it explicitly so it balloons on small hosts too.
    router = {"template": "debian-12-x64-server-template",
              "ram_gb": 2, "ram_min_gb": 1,
              **(topo.get("router") or {})}
    # balloon floor must stay strictly below the memory cap or PVE rejects
    # the options update — clamp lopsided specs (incl. generated quests)
    for spec in (*vms, router):
        lo, hi = spec.get("ram_min_gb"), spec.get("ram_gb")
        if lo and hi and lo >= hi:
            spec["ram_min_gb"] = max(1, hi // 2)
    cfg: dict = {"ludus": vms, "router": router}
    # platform control plane: the range must reach the app VM's address on
    # the ludus "public" bridge (telemetry + terminal channel dial it).
    # That is handled by the testing-mode allow list — destination-based
    # ACCEPTs installed with the isolation at finalize. Ludus rules cannot
    # express it: vlan_dst=public only renders bare ("! range/16"), and
    # ip_last_octet_dst interpolates into 10.x.<vlan>.<octet> — literally
    # "10.1.public.10" — which fails the deploy's firewall task outright.
    return cfg


# ---------------- resource gate ----------------
#
# Quest requirements used to compare against three STATIC admin budgets
# (resources.max_*). On a ballooning host that under-sells badly: the range
# footprint that actually matters is the ram_min_gb floor (balloon target),
# not the headline ram_gb sum — and vcpus oversubscribe freely since range
# VMs idle most of the time.
#
# resources.gate_mode:
#   "live"   — probe node_status + storage + template list (default)
#   "static" — legacy: requirements vs resources.max_* budgets
#   "off"    — no resource gate (progression still applies)
#
# Live knobs: resources.ram_headroom (fraction of FREE ram the floor must
# fit under, default 0.85), resources.vcpu_overcommit (vcpus vs host cores,
# default 4).

_HOST_CAP_TTL_S = 25.0
_host_cap: dict | None = None
_host_cap_at = 0.0
_templates_at = 0.0
_templates: set[str] | None = None


def _range_footprint(quest: Quest) -> dict:
    """Effective range footprint — ballooning-aware.

    ram_floor_gb = Σ ram_min_gb (the value the VM may shrink to — the real
    need); ram_nominal_gb = Σ ram_gb (headline); vcpus = Σ cpus + router(1).
    """
    topo = quest.topology or {}
    kali = topo.get("kali") or {}
    floor = (kali.get("ram_min_gb")
             or max(1, kali.get("ram_gb", 6) // 2)) + 1  # router ram_min
    nominal = kali.get("ram_gb", 6) + 2
    vcpus = kali.get("cpus", 4) + 1
    for v in topo.get("vms") or []:
        ram_gb = v.get("ram_gb", 4)
        floor += v.get("ram_min_gb") or max(1, ram_gb // 2)
        nominal += ram_gb
        vcpus += v.get("cpus", 2)
    return {"ram_floor_gb": floor, "ram_nominal_gb": nominal, "vcpus": vcpus}


async def _host_capacity(engine) -> dict | None:
    """node_status → {ram_free_gb, cores, disk_free_gb}, cached ~25s."""
    global _host_cap, _host_cap_at
    now = asyncio.get_event_loop().time()
    if _host_cap is not None and now - _host_cap_at < _HOST_CAP_TTL_S:
        return _host_cap
    cap = None
    try:
        node = await engine.pve.node_status()
        mem = node.get("memory") or {}
        total = (mem.get("total") or 0) / 2**30
        used = (mem.get("used") or 0) / 2**30
        disk = 0.0
        try:
            for p in await engine.pve.storage_pools():
                if p.get("active") and "images" in (p.get("content") or ""):
                    disk = max(disk, (p.get("avail") or 0) / 2**30)
        except Exception:
            pass
        cap = {"ram_free_gb": max(0.0, total - used),
               "cores": int((node.get("cpuinfo") or {}).get("cpus") or 0),
               "disk_free_gb": disk}
    except Exception:
        pass
    _host_cap, _host_cap_at = cap, now
    return cap


async def _host_templates(engine) -> set[str] | None:
    """Template names on the node, cached ~25s. None on PVE failure."""
    global _templates, _templates_at
    now = asyncio.get_event_loop().time()
    if _templates is not None and now - _templates_at < _HOST_CAP_TTL_S:
        return _templates
    names = None
    with contextlib.suppress(Exception):
        names = {v["name"] for v in await engine.pve.cluster_vms()
                 if v.get("template") and v.get("name")}
    _templates, _templates_at = names, now
    return names


def _quest_templates(quest: Quest) -> set[str]:
    topo = quest.topology or {}
    names = {(topo.get("kali") or {}).get("template", "kali-x64-desktop-template"),
             (topo.get("router") or {}).get("template", "debian-12-x64-server-template")}
    names.update(v.get("template", "") for v in topo.get("vms") or [])
    names.discard("")
    return names


async def check_unlock(db: AsyncSession, quest: Quest) -> tuple[bool, str]:
    """Adaptive unlock: live-capacity resource gate + tier progression."""
    mode = str(await settings_svc.get_setting(db, "resources.gate_mode", "live") or "live")
    if mode == "static":
        req = quest.requirements or {}
        for key, req_key, unit in (
            ("resources.max_ram_gb", "min_ram_gb", "G RAM"),
            ("resources.max_vcpus", "min_vcpus", " vCPU"),
            ("resources.max_disk_gb", "min_disk_gb", "G disk"),
        ):
            try:
                budget = int(await settings_svc.get_setting(db, key, 0) or 0)
                need = int(req.get(req_key, 0) or 0)
            except (TypeError, ValueError):  # a bad setting shouldn't brick unlock checks
                continue
            if need > budget:
                return False, f"requires {need}{unit} (budget {budget})"
    elif mode == "live":
        try:
            engine = await get_engine(db)
            if engine.mode != "mock" and getattr(engine, "pve", None):
                tpls = await _host_templates(engine)
                if tpls is not None:
                    missing = sorted(_quest_templates(quest) - tpls)
                    if missing:
                        return False, (f"template {missing[0]} not on host — "
                                       f"build it (packer) or pick another quest")
                cap = await _host_capacity(engine)
                if cap is not None:
                    foot = _range_footprint(quest)
                    headroom = float(await settings_svc.get_setting(
                        db, "resources.ram_headroom", 0.85) or 0.85)
                    overcommit = float(await settings_svc.get_setting(
                        db, "resources.vcpu_overcommit", 4.0) or 4.0)
                    req = quest.requirements or {}
                    if foot["ram_floor_gb"] > cap["ram_free_gb"] * headroom:
                        return False, (f"needs {foot['ram_floor_gb']:.0f}G free RAM "
                                       f"(host free {cap['ram_free_gb']:.0f}G)")
                    if cap["cores"] and foot["vcpus"] > cap["cores"] * overcommit:
                        return False, (f"needs {foot['vcpus']} vCPU "
                                       f"(host {cap['cores']} cores x{overcommit:g})")
                    disk_need = int(req.get("min_disk_gb", 0) or 0)
                    if cap["disk_free_gb"] and disk_need > cap["disk_free_gb"]:
                        return False, (f"needs {disk_need}G disk "
                                       f"(host free {cap['disk_free_gb']:.0f}G)")
        except Exception:
            # engine unavailable → don't brick quests on an infra hiccup
            pass
    # mode == "off" → no resource gate
    # generated (builder) quests carry no track progression — tier/exam
    # gates would dead-lock them since the custom track has no ladder.
    if not quest.generated and (quest.tier > 1 or quest.exam):
        solved_ids = await solved_quest_ids(db)
    if quest.tier > 1 and not quest.generated:
        # any non-exam quest at the previous tier unlocks this one —
        # exams are capstones, not stepping stones
        prevs = (await db.execute(
            select(Quest.id).where(Quest.track_slug == quest.track_slug,
                                   Quest.tier == quest.tier - 1,
                                   Quest.exam.is_not(True)))).scalars().all()
        if prevs and not any(p in solved_ids for p in prevs):
            return False, f"solve a tier {quest.tier - 1} quest in this track first"
    if quest.exam and not quest.generated:
        # capstone gate: every non-exam quest at this tier must be solved
        peers = (await db.execute(
            select(Quest.id).where(Quest.track_slug == quest.track_slug,
                                   Quest.tier == quest.tier,
                                   Quest.exam.is_not(True)))).scalars().all()
        missing = [p for p in peers if p not in solved_ids]
        if missing:
            done = len(peers) - len(missing)
            return False, (f"exam: solve all tier {quest.tier} quests first "
                           f"({done}/{len(peers)} done)")
    return True, ""


async def active_session(db: AsyncSession) -> Session | None:
    return (await db.execute(
        select(Session).where(Session.state.in_([
            SessionState.QUEUED.value, SessionState.DEPLOYING.value,
            SessionState.READY.value, SessionState.ACTIVE.value,
            SessionState.RESETTING.value]))
        .order_by(Session.id.desc()).limit(1))).scalar_one_or_none()


# ---------------- lifecycle ----------------

async def create_session(db: AsyncSession, quest_id: str,
                         autonomy_level: int | None = None,
                         subagents_enabled: bool = False) -> Session:
    async with _create_lock:  # one active session at a time — no TOCTOU
        quest = await db.get(Quest, quest_id)
        if not quest or not quest.active:
            raise SessionError(f"quest {quest_id} not found/inactive")
        ok, reason = await check_unlock(db, quest)
        if not ok:
            raise SessionError(f"quest locked: {reason}")
        if await active_session(db):
            raise SessionError("another session is active — abort it first")
        # caller-supplied autonomy must land in the FIRST commit — the
        # deploy task + coach context read the row immediately; setting it
        # after commit races them into the default level (s2: attached at 2)
        autonomy = (int(autonomy_level) if autonomy_level else
                    int(await settings_svc.get_setting(
                        db, "coach.default_autonomy", 2)))
        coach_enabled = bool(await settings_svc.get_setting(db, "coach.enabled", True))
        session = Session(
            quest_id=quest_id, state=SessionState.QUEUED.value,
            flag_seed=new_seed(), telemetry_token=new_telemetry_token(),
            autonomy_level=autonomy, coach_enabled=coach_enabled,
            subagents_enabled=bool(subagents_enabled),
        )
        db.add(session)
        await db.commit()
    await _broadcast(session.id, "state", {"state": session.state})
    _tasks[session.id] = asyncio.create_task(_deploy(session.id))
    return session


async def _deploy(session_id: int) -> None:
    try:
        if not _own(session_id):
            return  # displaced by a newer reset/abort — don't double-deploy
        async with session_factory()() as db:
            session = await db.get(Session, session_id)
            if not session:
                return
            try:
                engine = await get_engine(db)
                await _set_state(db, session, SessionState.DEPLOYING)
                if await _wait_for_aborts(db, session.id):
                    # the wait rolled the tx back — `session` is expired
                    session = await db.get(Session, session_id)
                quest = await db.get(Quest, session.quest_id)
                await _append_log(db, session, "[pentrain] compiling topology → ludus config")
                config = compile_topology(
                    quest,
                    kali_template=await settings_svc.get_setting(
                        db, "engine.kali_template", "") or None)
                await _append_log(db, session, yaml.safe_dump(config, sort_keys=False).rstrip())
                session.range_id = await engine.provider.deploy_range(f"quest-{quest.id}", config)
                await db.commit()

                st = await _watch_range(db, engine, session)
                await _finalize(db, engine, session, quest, st)
            except _Displaced:
                return  # newer owner manages this session now
            except Exception as e:
                await log.aexception("deploy failed", session_id=session_id)
                # str() of transport exceptions (httpx.ReadTimeout) is EMPTY —
                # repr keeps the type name so the error field is never blank.
                detail = f"{type(e).__name__}: {e}" if str(e) else repr(e)
                with contextlib.suppress(Exception):
                    await _append_log(db, session, f"[pentrain] deploy failed: {detail}")
                await _set_state(db, session, SessionState.FAILED, error=detail)
    finally:
        if _own(session_id):
            _tasks.pop(session_id, None)


async def _wait_for_aborts(db: AsyncSession, sid: int) -> bool:
    """Hold a fresh deploy until any in-flight range teardown settles.

    All sessions share ONE ludus default range — PUT config + POST deploy on a
    range whose destroy is still running corrupts the deploy server-side
    (observed: 'Unable to add VM to database: name: cannot be blank', then the
    range vanished mid-deploy and the session watched an absent range for the
    full 45min timeout). Poll other sessions' ABORTING state — that flag is the
    authoritative teardown-in-progress signal — with a bounded wait so a wedged
    abort cannot deadlock every future session.

    Returns True when a wait actually happened — each poll ends the tx via
    rollback so fresh abort states are visible, which EXPIRES every ORM object
    in `db` (callers must re-fetch)."""
    def _aborting_ids():
        return select(Session.id).where(
            Session.state == SessionState.ABORTING.value,
            Session.id != sid)

    other_aborting = (await db.execute(_aborting_ids())).scalars().all()
    if not other_aborting:
        return False
    await _append_log_by_id(db, sid,
                            f"[pentrain] waiting for {len(other_aborting)} teardown(s) before deploy")
    # ~15min ceiling — teardown of the biggest range takes far less; beyond
    # that the abort task is stuck and the deploy would race a dead range.
    for _ in range(15 * 6):
        await asyncio.sleep(POLL_S)
        await db.rollback()  # drop the snapshot — see fresh abort states
        still = (await db.execute(_aborting_ids())).scalars().all()
        if not still:
            return True
    raise SessionError("previous range teardown did not finish — abort it again")


async def _watch_range(db: AsyncSession, engine, session: Session,
                       seen_log_seed: str = ""):
    """Poll ludus until the range is RUNNING (max ~45 min for big AD labs).

    `seen_log_seed` lets the resume path skip lines already persisted before a
    backend restart, so the deploy log continues instead of repeating. Status
    failures are tolerated — a flaky API must not kill a 30-minute deploy."""
    seen_log = seen_log_seed
    consec_errors = 0
    consec_absent = 0
    for _ in range(45 * 6):
        if not _own(session.id):
            raise _Displaced()  # a newer lifecycle task owns this session
        try:
            st = await engine.provider.status(session.range_id or None)
        except Exception as e:
            consec_errors += 1
            if consec_errors >= 6:
                raise SessionError(f"range status unreachable: {e}") from e
            await asyncio.sleep(POLL_S)
            continue
        consec_errors = 0
        tail = st.log_tail or ""
        if tail != seen_log:
            new = tail[len(seen_log):] if tail.startswith(seen_log) else "\n" + tail
            seen_log = tail
            for line in new.strip("\n").splitlines():
                if line.strip():
                    await _append_log(db, session, line)
        if st.state == RangeState.RUNNING:
            return st
        if st.state == RangeState.FAILED:
            raise SessionError("range deploy failed — see deploy log")
        if st.state == RangeState.ABSENT:
            # the range object vanished after deploy_range returned — a
            # concurrent teardown deleted it mid-deploy (shared default range).
            # Grace of 3 polls absorbs a transient 404; then fail fast instead
            # of polling an absent range for the full timeout.
            consec_absent += 1
            if consec_absent >= 3:
                raise SessionError("range disappeared mid-deploy (concurrent teardown?)")
        else:
            consec_absent = 0
        await asyncio.sleep(POLL_S)
    raise SessionError("deploy timed out")


async def _inject_llm_envs(db: AsyncSession, engine, session: Session,
                           quest: Quest) -> None:
    """Write /etc/pentrain-llm.env on every inference-enabled VM and restart
    its declared unit. Runs at finalize AND after soft reset — reset
    regenerates telemetry_token, so a stale URL would 403."""
    api_ip, api_port = _api_ip_port(
        await settings_svc.get_setting(db, "platform.api_url", ""))
    for v in (quest.topology or {}).get("vms") or []:
        if not v.get("inference") or not api_ip:
            continue
        vmid = (session.target_vmids or {}).get(v["name"])
        if not vmid or not getattr(engine, "pve", None):
            continue
        try:
            await engine.pve.agent_file_write(
                vmid, "/etc/pentrain-llm.env",
                f"PENTRAIN_LLM_URL=http://{api_ip}:{api_port}"
                f"/api/llm-proxy/{session.telemetry_token}\n")
            svc = v["inference"].get("service") \
                if isinstance(v["inference"], dict) else None
            if svc:
                await engine.pve.agent_exec_sh(
                    vmid, f"systemctl try-restart {svc}", timeout_s=20)
            await _append_log(db, session,
                              f"[pentrain] llm-proxy env -> {v['name']}")
        except Exception as e:
            await _append_log(db, session,
                              f"[pentrain] llm-proxy env {v['name']} warn: {e!r}")


async def _run_vm_setup(db: AsyncSession, engine, session: Session,
                        quest: Quest) -> None:
    """Apply each VM's `setup:` spec — builder-generated customization that
    drops files + runs execs on the target via qemu-guest-agent. Same trust
    level as ansible roles (it IS quest content); every step lands in the
    deploy log so the builder's diagnose loop gets honest evidence. Non-fatal
    per step — a broken setup must not wedge the range, the verify pass
    catches it downstream."""
    if not getattr(engine, "pve", None):
        return
    import base64
    for v in (quest.topology or {}).get("vms") or []:
        setup = v.get("setup")
        if not setup:
            continue
        vmid = (session.target_vmids or {}).get(v["name"])
        if not vmid:
            await _append_log(db, session,
                              f"[pentrain] setup skipped — no vmid for {v['name']}")
            continue
        for f in setup.get("files") or []:
            try:
                raw = f.get("content")
                if raw is None and f.get("content_b64"):
                    raw = base64.b64decode(f["content_b64"]).decode(
                        "utf-8", errors="replace")
                await engine.pve.agent_file_write(vmid, f["path"], raw or "")
                mode = f.get("mode")
                if mode:
                    await engine.pve.agent_exec_sh(
                        vmid, f"chmod {mode} {f['path']}", timeout_s=10)
                await _append_log(db, session,
                                  f"[pentrain] setup file -> {v['name']}:{f['path']}")
            except Exception as e:
                await _append_log(db, session,
                                  f"[pentrain] setup file {f['path']} FAILED: {e!r}")
        for cmd in setup.get("exec") or []:
            try:
                res = await engine.pve.agent_exec_sh(vmid, cmd, timeout_s=600)
                code = res.get("exitcode")
                tail = (res.get("out") or res.get("err") or "").strip()[-400:]
                await _append_log(
                    db, session,
                    f"[pentrain] setup exec {v['name']}$ {cmd[:160]} "
                    f"-> exit {code}"
                    + (f" | {tail[:300]}" if tail and code else ""))
            except Exception as e:
                await _append_log(db, session,
                                  f"[pentrain] setup exec FAILED on {v['name']}: "
                                  f"{cmd[:120]} — {e!r}")


async def _finalize(db: AsyncSession, engine, session: Session,
                    quest: Quest, st) -> None:
    """RUNNING range → ready session. Idempotent — the resume path may re-run
    telemetry/flags/snapshot on a range that already passed through here."""
    if not _own(session.id):
        return  # displaced — a newer lifecycle task owns this session now
    await db.commit()
    kali = next((v for v in st.vms if v.role == "kali" or "kali" in v.name.lower()), None)
    session.kali_vmid = kali.vmid if kali else None
    # map short names → vmid. Ludus VM names are "<range_id>-<vmname>" —
    # strip the WHOLE range prefix (the first-dash split used to leave
    # "linux-t1-…-target01" which never matched topology names like
    # "target01", so file-flag injection and target telemetry silently
    # skipped every named target VM)
    rid = (session.range_id or "").lower()
    def _short(name: str) -> str:
        n = name.lower()
        if rid and n.startswith(rid + "-"):
            return n[len(rid) + 1:]
        return n.rsplit("-", 1)[-1]
    session.target_vmids = {
        _short(v.name): v.vmid for v in st.vms if v is not kali and v.vmid}
    await _append_log(db, session, f"[pentrain] range RUNNING — kali vmid={session.kali_vmid}")

    # Ludus flips the range to RUNNING while VMs are still booting — every
    # QGA step below (telemetry, hosts pin, tool probe, net1 hot-plug) needs
    # the guest up first. Non-fatal: per-step guards still degrade on their own.
    if session.kali_vmid and getattr(engine, "pve", None):
        try:
            pve = engine.pve
            for _ in range(90):                       # ~3min for slow clones
                st = (await pve.vm_status(session.kali_vmid)).get("status")
                if st == "running":
                    break
                if st == "stopped":
                    with contextlib.suppress(Exception):  # locked/starting → keep polling
                        await pve.vm_start(session.kali_vmid)
                await asyncio.sleep(2)
            if not await pve.wait_agent(session.kali_vmid, 120):
                await _append_log(db, session,
                                  "[pentrain] kali guest agent slow — QGA steps may warn")
        except Exception as e:
            await _append_log(db, session, f"[pentrain] kali boot wait warn: {e!r}")

    # telemetry config + short-name resolution on kali and all linux targets
    if session.kali_vmid:
        await _configure_telemetry(db, engine, session, quest)
        await _pin_range_hosts(db, engine, session, quest)
        # live tool inventory for the coach — stops "command not found"
        # discoveries mid-run. Non-fatal: QGA may be late on slow boots.
        try:
            res = await engine.pve.agent_exec_sh(
                session.kali_vmid,
                "for t in " + " ".join(KALI_TOOL_PROBE) +
                "; do command -v $t >/dev/null 2>&1 && echo $t; done",
                timeout_s=15)
            session.kali_tools = (res.get("out") or "").strip()
            await db.commit()
        except Exception:
            pass

    # per-vm post-deploy customization — builder quests drop files + run
    # execs via QGA (same channel as flag injection). Runs BEFORE flags so
    # a flag may land inside a setup-created path/container; everything is
    # pre-snapshot, so soft reset keeps the setup state.
    await _run_vm_setup(db, engine, session, quest)

    # dynamic flags
    quest_flags = (await db.execute(
        select(Flag).where(Flag.quest_id == quest.id))).scalars().all()
    await flags_svc.create_expected_flags(db, session, quest_flags)
    for line in await flags_svc.inject_flags(db, engine, session, quest_flags):
        await _append_log(db, session, f"[pentrain] {line}")

    # inference-enabled quest VMs get a session-scoped LLM proxy URL via an
    # env file + service restart. Guests reach /api/llm-proxy over the same
    # testing-allow route as telemetry — no range egress to the LLM host.
    await _inject_llm_envs(db, engine, session, quest)

    # kali wan uplink — BEFORE the snapshot so soft reset keeps the net1
    # config. Non-fatal: a missing DHCP lease must not sink the deploy.
    # topology.kali.wan = the quest REQUIRES the uplink (home-lab LAN mode)
    api_ip, _ = _api_ip_port(
        await settings_svc.get_setting(db, "platform.api_url", ""))
    want_net = (bool(session.kali_internet)
                or bool((quest.topology or {}).get("kali", {}).get("wan"))
                or bool(await settings_svc.get_setting(db, "kali.internet_default", False)))
    if want_net and session.kali_vmid:
        try:
            res = await kali_net_svc.apply_kali_internet(
                engine, session.kali_vmid,
                await settings_svc.get_setting(db, "engine.kali_wan_bridge", "vmbr0"),
                kali_net_svc.target_names_for(quest), api_host=api_ip)
            session.kali_internet = True
            # persist the LAN lease — coach scope auto-detect + UI display
            session.kali_wan_ip = res.get("ip") or None
            await db.commit()
            detail = f"{res.get('ip','?')} via {res.get('iface','?')}" if res.get("ip") else "mock"
            await _append_log(db, session, f"[pentrain] kali internet on ({detail})")
        except Exception as e:
            await _append_log(db, session, f"[pentrain] kali internet failed: {e}")

    # internet isolation + restore point (allow the app/telemetry endpoint)
    if bool(await settings_svc.get_setting(db, "engine.testing_mode", True)):
        allow = list(await settings_svc.get_setting(db, "engine.testing_allow", []))
        allow = _merge_testing_allow(allow, api_ip)
        await engine.provider.testing_mode(True, allow_ips=allow or None)
    await _append_log(db, session, "[pentrain] snapshotting range (soft-reset point)")
    await engine.provider.snapshot_all(session.range_id or None, SNAP_POST_DEPLOY)

    await _set_state(db, session, SessionState.READY,
                     ready_at=datetime.now(UTC).replace(tzinfo=None))


async def resume_inflight() -> int:
    """Reattach to sessions whose deploy/reset task died with the process.

    Ludus deploys server-side — a backend restart orphans the watcher, not the
    range. Called once from the app lifespan after packs are synced."""
    async with session_factory()() as db:
        rows = (await db.execute(
            select(Session).where(Session.state.in_([
                SessionState.QUEUED.value, SessionState.DEPLOYING.value,
                SessionState.RESETTING.value,
                SessionState.ABORTING.value])))).scalars().all()
        ids = [s.id for s in rows]
    for sid in ids:
        _tasks[sid] = asyncio.create_task(_resume(sid))
    if ids:
        await log.ainfo("inflight sessions resumed", sessions=ids)
    return len(ids)


async def _resume(session_id: int) -> None:
    """Decide per persisted state + live range status how to continue a
    session whose in-process task was lost (restart, crash)."""
    try:
        async with session_factory()() as db:
            session = await db.get(Session, session_id)
            if not session:
                return
            quest = await db.get(Quest, session.quest_id)
            try:
                engine = await get_engine(db)
                try:
                    st = await engine.provider.status(session.range_id or None)
                except Exception as e:
                    # engine unreachable at boot — leave the state alone so the
                    # next restart can try again instead of failing a live range
                    await log.awarning("resume status probe failed — leaving state",
                                       session_id=session_id, error=str(e))
                    return
                if not _own(session_id):
                    return  # displaced while probing — a newer lifecycle
                            # task owns the session now
                await _append_log(
                    db, session,
                    f"[pentrain] backend restarted — resuming (range {st.state.value})")
                if session.state == SessionState.ABORTING.value:
                    # teardown died with the process — finish it now
                    with contextlib.suppress(Exception):
                        await engine.provider.destroy_range(session.range_id)
                    await _set_state(db, session, SessionState.ABORTED,
                                     ended_at=datetime.now(UTC).replace(tzinfo=None))
                    return
                if session.state == SessionState.QUEUED.value or st.state == RangeState.ABSENT:
                    await _deploy(session_id)
                    return
                if st.state == RangeState.FAILED:
                    await _set_state(db, session, SessionState.FAILED,
                                     error="deploy failed while backend was down")
                    return
                if session.state == SessionState.RESETTING.value and st.state == RangeState.RUNNING:
                    await _reset(session_id, hard=True)
                    return
                if st.state == RangeState.DEPLOYING:
                    st = await _watch_range(db, engine, session,
                                            seen_log_seed=st.log_tail or "")
                if st.state == RangeState.RUNNING:
                    await _finalize(db, engine, session, quest, st)
            except _Displaced:
                return  # newer owner manages this session now
            except Exception as e:
                await log.aexception("resume failed", session_id=session_id)
                await _set_state(db, session, SessionState.FAILED, error=str(e))
    finally:
        if _own(session_id):
            _tasks.pop(session_id, None)


async def activate(db: AsyncSession, session_id: int) -> Session:
    session = await db.get(Session, session_id)
    if not session or session.state != SessionState.READY.value:
        raise SessionError("session not ready")
    await _set_state(db, session, SessionState.ACTIVE,
                     started_at=datetime.now(UTC).replace(tzinfo=None))
    db.add(CoachMessage(session_id=session.id, role="system", kind="chat",
                        content=f"Session started on quest {session.quest_id}."))
    await db.commit()
    return session


async def submit_flag(db: AsyncSession, session_id: int, value: str) -> dict:
    session = await db.get(Session, session_id)
    if not session or session.state != SessionState.ACTIVE.value:
        raise SessionError("session not active")
    engine = await get_engine(db)
    result = await flags_svc.submit_flag(db, engine, session, value)
    await _broadcast(session_id, "flag", result)
    if result["all_solved"]:
        await _set_state(db, session, SessionState.SOLVED,
                         ended_at=datetime.now(UTC).replace(tzinfo=None))
        attempt = await scoring_svc.finalize_attempt(db, session)
        await _broadcast_solved(session_id, attempt)
    return result


async def check_flag(db: AsyncSession, session_id: int, flag_key: str) -> dict:
    session = await db.get(Session, session_id)
    if not session or session.state != SessionState.ACTIVE.value:
        raise SessionError("session not active")
    engine = await get_engine(db)
    result = await flags_svc.check_and_record_flag(db, engine, session, flag_key)
    if err := result.pop("error", None):
        raise SessionError(err)
    await _broadcast(session_id, "flag", result)
    if result["all_solved"]:
        await _set_state(db, session, SessionState.SOLVED,
                         ended_at=datetime.now(UTC).replace(tzinfo=None))
        attempt = await scoring_svc.finalize_attempt(db, session)
        await _broadcast_solved(session_id, attempt)
    return result


async def use_hint(db: AsyncSession, session_id: int, hint_id: str) -> dict:
    session = await db.get(Session, session_id)
    if not session or session.state not in (SessionState.ACTIVE.value, SessionState.READY.value):
        raise SessionError("no active session")
    quest = await db.get(Quest, session.quest_id)
    hint = next((h for h in ((quest.hints_cfg if quest else []) or []) if h.get("id") == hint_id), None)
    if not hint:
        raise SessionError(f"unknown hint {hint_id}")
    db.add(HintUse(session_id=session_id, hint_id=hint_id, cost=int(hint.get("cost", 0))))
    await db.commit()
    await _broadcast(session_id, "hint", {"hint_id": hint_id, "cost": hint.get("cost")})
    return hint


async def reset(db: AsyncSession, session_id: int, *, hard: bool = False) -> Session:
    session = await db.get(Session, session_id)
    if not session or session.state in (SessionState.ABORTED.value, SessionState.FAILED.value,
                                        SessionState.ABORTING.value):
        raise SessionError("session not resettable")
    await _set_state(db, session, SessionState.RESETTING)
    _tasks[session.id] = asyncio.create_task(_reset(session.id, hard))
    return session


async def _reset(session_id: int, hard: bool) -> None:
    if not _own(session_id):
        return  # displaced by a newer lifecycle task
    async with session_factory()() as db:
        session = await db.get(Session, session_id)
        quest = await db.get(Quest, session.quest_id) if session else None
        try:
            engine = await get_engine(db)
            if hard:
                await _append_log(db, session, "[pentrain] hard reset: destroy + redeploy")
                await engine.provider.destroy_range(session.range_id)
                if not _own(session_id):
                    return  # displaced during teardown — don't double-deploy
                await _set_state(db, session, SessionState.QUEUED)
                _tasks[session_id] = asyncio.create_task(_deploy(session_id))
                return
            await _append_log(db, session, "[pentrain] soft reset: snapshot rollback")
            await engine.provider.rollback_all(session.range_id, SNAP_POST_DEPLOY)
            # rollback restores the snapshot's VM config — re-align net1 with
            # the session flag (toggle may have changed after the snapshot)
            if session.kali_vmid:
                try:
                    api_ip, _ = _api_ip_port(await settings_svc.get_setting(
                        db, "platform.api_url", ""))
                    if session.kali_internet:
                        res = await kali_net_svc.apply_kali_internet(
                            engine, session.kali_vmid,
                            await settings_svc.get_setting(
                                db, "engine.kali_wan_bridge", "vmbr0"),
                            kali_net_svc.target_names_for(quest) if quest else [],
                            api_host=api_ip)
                        session.kali_wan_ip = res.get("ip") or session.kali_wan_ip
                    else:
                        await kali_net_svc.remove_kali_internet(
                            engine, session.kali_vmid, api_host=api_ip)
                        session.kali_wan_ip = None
                except Exception as e:
                    await log.awarning("kali internet re-apply failed", error=str(e)[:150])
            # rollback wipes router iptables (disk-only snapshot) — re-apply
            # testing-mode isolation + the api allow rules or telemetry and
            # the terminal channel die with the reset
            if bool(await settings_svc.get_setting(db, "engine.testing_mode", True)):
                api_ip, _ = _api_ip_port(await settings_svc.get_setting(
                    db, "platform.api_url", ""))
                allow = list(await settings_svc.get_setting(
                    db, "engine.testing_allow", []))
                allow = _merge_testing_allow(allow, api_ip)
                try:
                    await engine.provider.testing_mode(
                        True, allow_ips=allow or None)
                except Exception as e:
                    await log.awarning("testing-mode re-apply failed",
                                       error=str(e)[:150])
            # per-attempt tables are cleared — a stale FlagSubmission would
            # instantly re-solve the run, a stale ended_at would clamp the
            # next duration to 0, and old hint/coach/telemetry rows would
            # corrupt the next attempt's assistance+intervention scoring.
            # The Attempt row and observer CoachLessons deliberately survive:
            # one is the run's record, the other cross-run knowledge.
            if not _own(session_id):
                return  # displaced mid-rollback — the new owner wipes
                        # per-attempt state itself
            for model in (FlagSubmission, HintUse, AssistUse, CoachAction,
                          CoachMessage, TelemetryEvent, CoachSessionState,
                          QuestCheckpoint):
                await db.execute(delete(model).where(
                    model.session_id == session_id))
            session.ended_at = None
            session.started_at = None
            # re-randomize flags (old secrets are gone after rollback)
            session.flag_seed = new_seed()
            session.telemetry_token = new_telemetry_token()
            await db.commit()
            if session.kali_vmid:
                await _configure_telemetry(db, engine, session, quest)
                await _pin_range_hosts(db, engine, session, quest)
            quest_flags = (await db.execute(
                select(Flag).where(Flag.quest_id == quest.id))).scalars().all()
            await flags_svc.create_expected_flags(db, session, quest_flags)
            for line in await flags_svc.inject_flags(db, engine, session, quest_flags):
                await _append_log(db, session, f"[pentrain] {line}")
            await _inject_llm_envs(db, engine, session, quest)
            if not _own(session_id):
                return  # displaced — don't flip a state the new owner manages
            await _set_state(db, session, SessionState.READY)
        except Exception as e:
            await log.aexception("reset failed", session_id=session_id)
            await _set_state(db, session, SessionState.FAILED, error=str(e))


def _linux_target_vmids(session: Session, quest: Quest | None) -> list[tuple[str, int]]:
    """(name, vmid) for every linux target VM — targets get the lightweight
    pentrain_target_agent so remote SSH commands feed telemetry too."""
    if not quest:
        return []
    out: list[tuple[str, int]] = []
    for v in (quest.topology or {}).get("vms") or []:
        if v.get("linux", True) and not v.get("windows") and not v.get("gpos"):
            vmid = (session.target_vmids or {}).get(v["name"])
            if vmid:
                out.append((v["name"], vmid))
    return out


def _range_hosts_script(quest: Quest | None) -> str | None:
    """Pin <name> + pentrain-<name> → 10.x.y.<octet> in /etc/hosts. Range IPs
    are deterministic; the guest derives its /24 from eth0 so no DNS lookup
    is needed. Runs on kali AND targets — pivot hops (ssh -J, tools run from
    a target) resolve short names the same way kali does."""
    pins: list[str] = ["kali:5", "pentrain-kali:5"]
    for i, v in enumerate((quest.topology or {}).get("vms") or []):
        name = v.get("name")
        if not name:
            continue
        octet = v.get("ip_last_octet") or 20 + i
        pins += [f"{name}:{octet}", f"pentrain-{name}:{octet}"]
    names = " ".join(pins)
    # pure ASCII only — guest-file-write dies on wide chars inside pvedaemon
    return f"""SUB=$(ip -4 -o addr show dev eth0 | awk '{{split($4,a,"/"); split(a[1],o,"."); \\
       print o[1]"."o[2]"."o[3]; exit}}')
[ -z "$SUB" ] && exit 0
grep -v ' # pentrain-range$' /etc/hosts > /tmp/h && cat /tmp/h > /etc/hosts
for p in {names}; do
  n=${{p%:*}}; o=${{p##*:}}
  echo "$SUB.$o $n # pentrain-range" >> /etc/hosts
done
"""


async def _configure_telemetry(db: AsyncSession, engine, session: Session,
                               quest: Quest | None = None) -> None:
    """(Re)write telemetried.conf on kali AND every linux target, then restart
    the agents. HOST= names the box so the backend can tell kali-side commands
    from commands typed inside a target SSH session."""
    api_url = await settings_svc.get_setting(db, "platform.api_url", "http://pentrain-app:8000")
    boxes = [("kali", session.kali_vmid), *_linux_target_vmids(session, quest)]
    for host, vmid in boxes:
        if not vmid:
            continue
        conf = (f"TOKEN={session.telemetry_token}\nSESSION={session.id}\n"
                f"HOST={host}\nAPI={api_url}\n"
                # SHELL=1 enables the browser-terminal channel — kali only;
                # targets share the telemetry token and must not offer shells.
                + ("SHELL=1\n" if host == "kali" else ""))
        try:
            await engine.pve.agent_write_file(vmid, "/etc/pentrain/telemetried.conf", conf)
            await engine.pve.agent_exec_sh(
                vmid, "systemctl restart pentrain-telemetried || true")
        except Exception as e:
            await _append_log(db, session, f"[pentrain] telemetry setup warn ({host}): {e}")


async def _pin_range_hosts(db: AsyncSession, engine, session: Session,
                           quest: Quest | None = None) -> None:
    """Write /etc/hosts pins for all range names on kali + linux targets."""
    script = _range_hosts_script(quest)
    if not script:
        return
    boxes = [("kali", session.kali_vmid), *_linux_target_vmids(session, quest)]
    for host, vmid in boxes:
        if not vmid:
            continue
        try:
            await engine.pve.agent_file_write(vmid, "/tmp/pentrain-hosts.sh", script)
            await engine.pve.agent_exec_sh(vmid, "sh /tmp/pentrain-hosts.sh", timeout_s=15)
        except Exception as e:
            await _append_log(db, session, f"[pentrain] hosts pin warn ({host}): {e}")


async def solved_quest_ids(db: AsyncSession) -> set[str]:
    """Quests that were ever fully solved. Anchored on finalized Attempts
    (created only on all_solved), NOT session.state — abort() legitimately
    tears down a solved session's range and must not erase progression."""
    return {r[0] for r in (await db.execute(select(Attempt.quest_id).distinct())).all()}


LEVEL_NAMES = {1: "Observer", 2: "Mentor", 3: "Copilot", 4: "Autonomous"}


async def set_autonomy(db: AsyncSession, session_id: int, level: int) -> Session:
    """Live-switch the coach autonomy level mid-session. The coach reads it
    fresh from session_context every turn, so a DB write + broadcast is all
    it takes — no coach-side plumbing needed."""
    session = await db.get(Session, session_id)
    if not session:
        raise SessionError("no session")
    if session.state in (SessionState.SOLVED.value, SessionState.ABORTED.value,
                         SessionState.FAILED.value,
                         SessionState.ABORTING.value):
        raise SessionError(f"session is {session.state} — autonomy is locked")
    if not 1 <= level <= 4:
        raise SessionError("autonomy level must be 1-4")
    session.autonomy_level = level
    await db.commit()
    await coach_bridge.post_message(
        db, session_id, "system", "chat",
        f"Autonomy level → {level} ({LEVEL_NAMES[level]}).")
    await _broadcast(session_id, "autonomy", {"level": level})
    return session


async def set_subagents(db: AsyncSession, session_id: int,
                        enabled: bool) -> Session:
    """Live-switch parallel worker agents mid-session — same propagation
    path as autonomy (context read + WS event), no coach-side plumbing."""
    session = await db.get(Session, session_id)
    if not session:
        raise SessionError("no session")
    if session.state in (SessionState.SOLVED.value, SessionState.ABORTED.value,
                         SessionState.FAILED.value,
                         SessionState.ABORTING.value):
        raise SessionError(f"session is {session.state} — subagents locked")
    session.subagents_enabled = enabled
    await db.commit()
    state = ("enabled — the coach can delegate parallel work to worker "
             "panes w1-w3" if enabled
             else "disabled — running workers were stopped")
    await coach_bridge.post_message(
        db, session_id, "system", "chat", f"Subagents {state}.")
    await _broadcast(session_id, "subagents", {"enabled": enabled})
    return session


async def set_coach_enabled(db: AsyncSession, session_id: int,
                            enabled: bool) -> Session:
    """Per-session pause/resume for the whole coach — the loop reads
    coach_enabled from session_context every tick and idles completely
    (no thinking either, unlike an autonomy drop). Range and kali stay
    up; resume picks up where it paused."""
    session = await db.get(Session, session_id)
    if not session:
        raise SessionError("no session")
    if session.state in (SessionState.SOLVED.value, SessionState.ABORTED.value,
                         SessionState.FAILED.value,
                         SessionState.ABORTING.value):
        raise SessionError(f"session is {session.state} — coach is locked")
    session.coach_enabled = enabled
    await db.commit()
    await coach_bridge.post_message(
        db, session_id, "system", "chat",
        "Coach resumed." if enabled else "Coach paused — range stays up.")
    await _broadcast(session_id, "coach_enabled", {"enabled": enabled})
    return session


async def abort(db: AsyncSession, session_id: int) -> Session:
    session = await db.get(Session, session_id)
    if not session:
        raise SessionError("no session")
    if session.state == SessionState.ABORTING.value:
        raise SessionError("abort already in progress")
    task = _tasks.get(session_id)
    if task and not task.done():
        task.cancel()
    # range destroy takes 60s+ on multi-VM topologies — a synchronous call
    # blows through the nginx proxy timeout (504) while the teardown keeps
    # running behind it. Transitional state + background task like reset().
    await _set_state(db, session, SessionState.ABORTING)
    _tasks[session.id] = asyncio.create_task(_abort(session.id))
    return session


async def _abort(session_id: int) -> None:
    try:
        async with session_factory()() as db:
            session = await db.get(Session, session_id)
            if not session:
                return
            try:
                engine = await get_engine(db)
                await engine.provider.destroy_range(session.range_id)
            except Exception as e:
                await log.awarning("destroy failed", error=str(e))
            await _set_state(db, session, SessionState.ABORTED,
                             ended_at=datetime.now(UTC).replace(tzinfo=None))
    finally:
        if _own(session_id):
            _tasks.pop(session_id, None)


async def suggest_command_confirm(db: AsyncSession, session_id: int, action_id: int,
                                  accept: bool) -> CoachAction:
    """Copilot (L3): user confirms/rejects a coach-suggested command."""
    action = await db.get(CoachAction, action_id)
    if not action or action.session_id != session_id:
        raise SessionError("action not found")
    if action.status != "pending":
        raise SessionError("action already resolved")
    session = await db.get(Session, session_id)
    if accept and (not session
                   or session.state not in (SessionState.ACTIVE.value, SessionState.READY.value)):
        raise SessionError("session not active")
    if accept:
        engine = await get_engine(db)
        cmd = action.args.get("command", "")
        try:
            # the confirmed command can run for a while — surface it in the UI
            await publish_session(session_id, "coach_activity", {
                "active": True,
                "text": f"executing confirmed `{cmd[:110]}`"}, sticky=True)
            # user-approved commands run visibly in the coach tmux as well
            res = await coach_bridge.exec_visible_in_kali(
                engine, session.kali_vmid, cmd, session_id=session_id) \
                if session.kali_vmid else {"out": "", "err": "no kali vmid", "exitcode": 1}
            action.result = res
            action.status = "confirmed"
            # surface the output in chat like a coach-executed command —
            # a confirmed suggestion that only says "executed" teaches nothing
            out = (res.get("out") or res.get("err") or "")[:500]
            note = ("\n\n*(typed live in the `pentrain-coach` tmux)*"
                    if res.get("visible") else "")
            await coach_bridge.post_message(
                db, session_id, "coach", "action_report",
                f"Executed (your confirmation): `{cmd}`\n```\n{out}\n```{note}")
        except Exception as e:
            action.result = {"error": str(e)}
            action.status = "error"
        finally:
            await publish_session(session_id, "coach_activity",
                                  {"active": False, "text": ""})
    else:
        action.status = "rejected"
    await db.commit()
    # mark the suggestion message resolved so the UI state survives reloads
    msg = (await db.execute(
        select(CoachMessage).where(
            CoachMessage.session_id == session_id,
            CoachMessage.kind == "suggestion",
            CoachMessage.meta["action_id"].as_integer() == action_id))).scalar_one_or_none()
    if msg:
        msg.meta = {**(msg.meta or {}), "resolved": action.status}
        await db.commit()
    await _broadcast(session_id, "coach_action", {"id": action.id, "status": action.status})
    return action
