"""Quest pack loader: content/packs/<track>/<quest-dir>/{quest.yaml, defense.md, ...}

Validated with pydantic, synced into DB (tracks/quests/flags). Quest dirs are the
source of truth — DB rows are re-written on each sync.
"""
from __future__ import annotations

from pathlib import Path

import structlog
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.domain import Flag, FlagKind, Quest, Track

log = structlog.get_logger(__name__)


# ---------------- schema ----------------

class Requirements(BaseModel):
    min_ram_gb: int = 8
    min_vcpus: int = 4
    min_disk_gb: int = 40
    est_deploy_min: int = 10
    needs_windows: bool = False


class KaliSpec(BaseModel):
    template: str = "kali-x64-desktop-template"
    ram_gb: int = 6
    ram_min_gb: int | None = None  # ballooning floor — compile_topology defaults to 3
    cpus: int = 4
    wan: bool = False              # auto-attach net1→WAN bridge (LAN/internet) at deploy
    roles: list[dict | str] = Field(default_factory=list)  # extra roles on kali


class VmSpec(BaseModel):
    name: str
    template: str
    ram_gb: int = 4
    ram_min_gb: int | None = None  # ballooning floor — defaults to ram_gb//2
    cpus: int = 2
    disk_gb: int | None = None
    vlan: int = 10
    ip_last_octet: int | None = None
    # platform LLM access — finalize injects PENTRAIN_LLM_URL (session-
    # scoped proxy) and restarts the named systemd unit, if given
    inference: dict | bool | None = None
    linux: bool = True
    windows: dict | None = None
    domain: dict | None = None
    roles: list[dict | str] = Field(default_factory=list)
    gpos: list[str] = Field(default_factory=list)

    @field_validator("vlan")
    @classmethod
    def _vlan_ok(cls, v: int) -> int:
        if not (2 <= v <= 255):
            raise ValueError("vlan must be 2..255")
        return v


class Topology(BaseModel):
    kali: KaliSpec = Field(default_factory=KaliSpec)
    vms: list[VmSpec] = Field(default_factory=list)
    networks: list[dict] = Field(default_factory=list)
    # engagement packs: targets come from the session scope snapshot
    # (POST /sessions/{id}/scope), never from the pack itself — the coach
    # must deny everything until an operator locks a whitelist
    engagement: bool = False


class FlagSpec(BaseModel):
    id: str
    name: str
    kind: str = "file"
    points: int = 100
    file_path: str | None = None          # where to inject on which vm
    vm: str | None = None
    container: str | None = None          # docker container on vm (inject/check via docker exec)
    command: dict | None = None           # kind=command: {vm, cmd, expect, container?}


class HintSpec(BaseModel):
    id: str
    cost: int = 25
    stage: str = "general"
    text: str


class CheckpointSpec(BaseModel):
    id: str
    name: str
    detect: dict = Field(default_factory=dict)  # {command_match: regex}
    hint_after_s: int = 600


class CoachCfg(BaseModel):
    briefing_ref: str | None = None
    checkpoints: list[CheckpointSpec] = Field(default_factory=list)
    escalation: dict = Field(default_factory=lambda: {
        "observe_grace_s": 180, "nudge_s": 480, "hint_s": 900})


class ScoringCfg(BaseModel):
    base: int = 500
    time_bonus_max: int = 200
    par_s: int = 1800
    hint_cost: int = 0     # per-hint costs live on the hint specs
    takeover_cost: int = 150


class QuestMeta(BaseModel):
    id: str
    track: str
    tier: int = 1
    title: str
    version: int = 1
    exam: bool = False        # capstone — check_unlock requires all same-tier non-exam quests solved


class QuestYaml(BaseModel):
    apiVersion: str = "pentrain/v1"
    kind: str = "Quest"
    meta: QuestMeta
    display: dict = Field(default_factory=dict)
    requirements: Requirements = Field(default_factory=Requirements)
    topology: Topology = Field(default_factory=Topology)
    flags: list[FlagSpec] = Field(default_factory=list)
    hints: list[HintSpec] = Field(default_factory=list)
    coach: CoachCfg = Field(default_factory=CoachCfg)
    scoring: ScoringCfg = Field(default_factory=ScoringCfg)


TRACK_TITLES = {
    "linux-fundamentals": ("Linux Fundamentals", "Host services, misconfigurations, privilege escalation — from guided basics to multi-host chains.", "server", 10),
    "web-appsec": ("Web AppSec", "Web vulnerability classes from OWASP basics to chained auth-bypass scenarios.", "globe", 20),
    "network-recon": ("Network & Recon", "Discovery, enumeration, segmentation and pivoting across routed networks.", "radar", 30),
    "active-directory": ("Active Directory", "Domain attacks from a single DC to multi-forest corporate networks.", "building", 40),
    "forensics": ("Forensics", "Log triage, disk artifacts and full intrusion timelines on attacked ranges.", "search", 50),
    "scripting": ("Scripting & Automation", "Bash and Python glue code, automation and tooling for pentesters.", "terminal", 60),
    "wifi": ("Wireless", "WiFi recon, handshake capture and cracking on a simulated radio lab.", "wifi", 70),
    "home-lab": ("Home Lab", "Authorized assessment of your own LAN — discovery, enumeration, vuln scan, reporting.", "home", 80),
    "engagement": ("External Engagement", "Authorized real-target engagements — operator-scoped recon, validation and reporting.", "shield", 81),
    "cloud-native": ("Cloud Native", "Kubernetes and container attack paths — RBAC, service accounts, cluster escape.", "cloud", 82),
    "ai-security": ("AI Security", "Prompt injection, data exfiltration and tool misuse against LLM-backed apps.", "bot", 84),
    "exploits": ("Exploit & Vulnerability Analysis", "Safely analyze vulnerable-code patterns, binary hardening, CI/CD trust and CVE exposure.", "bug", 86),
    "capstone": ("Capstone", "Full engagement simulations — multi-tier networks, chained objectives, zero walkthroughs.", "crown", 90),
}


# ---------------- validation ----------------

def validate_quest_dir(qdir: Path) -> tuple[QuestYaml | None, list[str]]:
    """Parse+validate one quest dir. Returns (spec, errors)."""
    errs: list[str] = []
    qy_path = qdir / "quest.yaml"
    if not qy_path.exists():
        return None, [f"{qdir.name}: missing quest.yaml"]
    try:
        spec = QuestYaml.model_validate(yaml.safe_load(qy_path.read_text()))
    except ValidationError as e:
        return None, [f"{qdir.name}: {e}"]
    except yaml.YAMLError as e:
        return None, [f"{qdir.name}: invalid yaml: {e}"]
    if spec.kind != "Quest":
        errs.append(f"{qdir.name}: kind must be Quest")
    if not (qdir / "defense.md").exists():
        errs.append(f"{qdir.name}: missing mandatory defense.md")
    if spec.coach.briefing_ref and not (qdir / spec.coach.briefing_ref).exists():
        errs.append(f"{qdir.name}: coach.briefing_ref {spec.coach.briefing_ref} not found")
    # "kali" is a valid flag target for scripting quests — the trainee console
    # VM is resolved to session.kali_vmid at flag check/injection time
    vm_names = {v.name for v in spec.topology.vms} | {"kali"}
    windows_vms = {v.name for v in spec.topology.vms if v.windows or not v.linux}
    for v in spec.topology.vms:
        if v.ip_last_octet == 254:
            errs.append(f"{qdir.name}: vm {v.name} uses ip_last_octet 254 — "
                        "the range router owns it")
        if v.gpos and not (v.windows or not v.linux):
            errs.append(f"{qdir.name}: vm {v.name} sets gpos but isn't a windows vm")
    for f in spec.flags:
        if f.kind == "file":
            if not f.vm:
                errs.append(f"{qdir.name}: file flag {f.id} needs 'vm' (injection target)")
            elif f.vm not in vm_names:
                errs.append(f"{qdir.name}: flag {f.id} references unknown vm {f.vm}")
        elif f.kind == "command":
            cmd = f.command or {}
            if not cmd.get("cmd"):
                errs.append(f"{qdir.name}: command flag {f.id} needs command.cmd")
            if cmd.get("vm") and cmd["vm"] not in vm_names:
                errs.append(f"{qdir.name}: command flag {f.id} references unknown vm {cmd['vm']}")
            elif cmd.get("vm") in windows_vms:
                errs.append(
                    f"{qdir.name}: command flag {f.id} targets windows vm {cmd['vm']} "
                    "— command checks run a POSIX shell, use kind=file")
        else:
            errs.append(f"{qdir.name}: flag {f.id} has unknown kind {f.kind!r}")
    return spec, errs


def discover_quests(content_dir: Path) -> tuple[list[tuple[Path, QuestYaml]], list[str]]:
    out: list[tuple[Path, QuestYaml]] = []
    errors: list[str] = []
    for track_dir in sorted(content_dir.iterdir()) if content_dir.exists() else []:
        if not track_dir.is_dir() or track_dir.name.startswith((".", "_")):
            continue
        for qdir in sorted(track_dir.iterdir()):
            if not qdir.is_dir():
                continue
            spec, errs = validate_quest_dir(qdir)
            errors.extend(errs)
            if spec:
                out.append((qdir, spec))
    return out, errors


def _read(p: Path) -> str:
    return p.read_text() if p.exists() else ""


# ---------------- DB sync ----------------

async def sync_packs(db: AsyncSession, content_dir: str | Path) -> dict:
    root = Path(content_dir)
    found, errors = discover_quests(root)
    seen_tracks: set[str] = set()
    seen_quests: set[str] = set()

    for _, spec in found:
        track_slug = spec.meta.track
        seen_tracks.add(track_slug)
        title, desc, icon, order = TRACK_TITLES.get(track_slug, (track_slug, "", "target", 99))
        track = await db.get(Track, track_slug)
        sheet = _read(root / track_slug / "cheatsheet.md")
        if track is None:
            db.add(Track(slug=track_slug, title=title, description=desc, icon=icon,
                         order=order, cheatsheet_md=sheet))
        else:
            track.cheatsheet_md = sheet

    for qdir, spec in found:
        qid = spec.meta.id
        seen_quests.add(qid)
        coach_ctx = _read(qdir / spec.coach.briefing_ref) if spec.coach.briefing_ref else ""
        quest = await db.get(Quest, qid)
        payload = dict(
            track_slug=spec.meta.track, tier=spec.meta.tier, title=spec.meta.title,
            exam=spec.meta.exam,
            summary=spec.display.get("tagline", ""), pack_path=str(qdir),
            version=spec.meta.version, active=True,
            requirements=spec.requirements.model_dump(),
            topology=spec.topology.model_dump(),
            scoring_cfg=spec.scoring.model_dump(),
            hints_cfg=[h.model_dump() for h in spec.hints],
            coach_cfg=spec.coach.model_dump(),
            briefing_md=_read(qdir / "briefing.md"),
            defense_md=_read(qdir / "defense.md"),
            cheatsheet_md=_read(qdir / "cheatsheet.md"),
            coach_context_md=coach_ctx,
        )
        if quest is None:
            quest = Quest(id=qid, **payload)
            db.add(quest)
        else:
            for k, v in payload.items():
                setattr(quest, k, v)
        # flags: full replace
        await db.execute(delete(Flag).where(Flag.quest_id == qid))
        for f in spec.flags:
            db.add(Flag(
                quest_id=qid, key=f.id, name=f.name,
                kind=FlagKind.COMMAND.value if f.kind == "command" else FlagKind.FILE.value,
                points=f.points,
                command_spec={
                    "vm": f.vm, "file_path": f.file_path, "container": f.container,
                    **(f.command or {}),
                },
            ))
    await db.commit()

    # deactivate quests no longer on disk
    stale = await db.execute(select(Quest.id).where(~Quest.id.in_(seen_quests or {"__none__"})))
    for (qid,) in stale.all():
        q = await db.get(Quest, qid)
        if q:
            q.active = False
    await db.commit()
    await log.ainfo("pack sync done", quests=len(seen_quests), errors=len(errors))
    return {"quests": len(seen_quests), "tracks": len(seen_tracks), "errors": errors}
