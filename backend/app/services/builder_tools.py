"""Builder tool layer — catalog introspection, research, verify-exec.

Three tool groups the builder LLM may call during a turn (bounded by
settings.builder.tool_call_cap):

- catalog: quest_catalog / read_quest / list_roles / read_role /
  list_templates — read-only access to curated packs + ansible roles so the
  builder learns conventions from real exemplars.
- research: web_search / web_fetch / query_vuln_db / rss_feed /
  search_technique — proxied into the coach's standalone research modules
  via researchkit (SSRF-safe, key-free sources). Gated on
  settings.builder.web_enabled.
- verify: kali_exec — runs a shell command on the verification session's
  Kali over QGA. Only available while a verify run is attached; honors the
  shared DENIED_PATTERNS list.

Every tool returns a plain-text result; errors come back as `error: ...`
so the model can react instead of crashing the loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..models.domain import Quest, Session
from . import researchkit
from .coach_bridge import _is_denied

_MAX_READ = 24_000          # chars per file read (keeps context sane)
_MAX_LIST = 60              # rows per list call


def _fn(name, desc, props, req=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props,
                       "required": req or []}}}


BUILDER_TOOLS = [
    _fn("quest_catalog",
        "List curated quests (id, track, tier, title, roles used). Call this "
        "first to find a similar quest to learn from.", {}),
    _fn("read_quest",
        "Read a file from a curated quest pack: 'quest.yaml', 'briefing.md', "
        "'coach_context.md', 'defense.md', or a flag file name. Use it to "
        "copy structure/conventions from a working exemplar.",
        {"quest_id": {"type": "string"}, "file": {"type": "string"}},
        ["quest_id", "file"]),
    _fn("list_roles",
        "List ansible roles available for vm.roles in quest.yaml, with their "
        "meta description. These run at deploy time on the PVE host.",
        {}),
    _fn("read_role",
        "Read a file inside an ansible role, e.g. file='tasks/main.yml' or "
        "'meta/main.yml'. Shows exactly how existing roles install services, "
        "write flags, expose ports.",
        {"role": {"type": "string"}, "file": {"type": "string"}},
        ["role", "file"]),
    _fn("list_templates",
        "List files/ asset trees inside roles (service templates: docker "
        "apps, k8s manifests, configs). Helps decide whether a template "
        "already exists for what the user wants.",
        {}),
    _fn("web_search",
        "Search the web for technique docs, exploit writeups, product "
        "defaults (DDG + Marginalia). Returns title/url/snippet rows.",
        {"query": {"type": "string"},
         "max_results": {"type": "integer"}}, ["query"]),
    _fn("web_fetch",
        "Fetch and extract readable text from a URL. SSRF-guarded: public "
        "internet only.",
        {"url": {"type": "string"}}, ["url"]),
    _fn("query_vuln_db",
        "Structured vulnerability lookup: NVD CVEs matching a product/"
        "version string plus CISA KEV entries. Good for grounding a quest "
        "in a real CVE.", {"query": {"type": "string"}}, ["query"]),
    _fn("rss_feed",
        "Pull a curated feed: exploitdb, packetstorm, cisa-alerts, "
        "github-advisories, thehackernews, r-netsec — or 'list'.",
        {"feed": {"type": "string"}, "count": {"type": "integer"}},
        ["feed"]),
    _fn("search_technique",
        "Search technique references (HackTricks/PATT/OWASP/GTFOBins/LOLBAS "
        "excerpts) vendored with the coach — works offline. Query like "
        "'docker escape', 'suid privesc', 'jwt confusion'.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("kali_exec",
        "Run a shell command on the verification session's Kali (only "
        "available while a verify run is active). Use for service checks, "
        "searchsploit, reproducing what the coach saw.",
        {"command": {"type": "string"}, "timeout_s": {"type": "integer"}},
        ["command"]),
]

# subsets per phase
RESEARCH_TOOLS = {"web_search", "web_fetch", "query_vuln_db", "rss_feed",
                  "search_technique"}
CATALOG_TOOLS = {"quest_catalog", "read_quest", "list_roles", "read_role",
                 "list_templates"}
VERIFY_TOOLS = {"kali_exec"}


@dataclass
class ToolCtx:
    db: AsyncSession
    engine: object | None = None
    web_enabled: bool = True
    verify_session_id: int | None = None
    content_dir: Path = field(default_factory=lambda: Path(
        get_config().content_dir))
    roles_dir: Path = field(default_factory=lambda: Path(
        get_config().roles_dir))


def _repo_roles_dir() -> Path:
    # dev fallback when /ansible-roles isn't mounted
    return Path(__file__).resolve().parents[3] / "content" / "ansible-roles"


def _resolve_roles_dir(ctx: ToolCtx) -> Path:
    return ctx.roles_dir if ctx.roles_dir.is_dir() else _repo_roles_dir()


def _safe_under(root: Path, name: str) -> Path | None:
    try:
        p = (root / name).resolve()
        return p if str(p).startswith(str(root.resolve())) and p.is_file() \
            else None
    except Exception:
        return None


def _read(path: Path) -> str:
    try:
        text = path.read_text(errors="replace")
    except Exception as e:
        return f"error: {e!r}"
    if len(text) > _MAX_READ:
        return text[:_MAX_READ] + f"\n… [truncated at {_MAX_READ} chars]"
    return text


async def dispatch(ctx: ToolCtx, name: str, args: dict) -> str:
    try:
        if name == "quest_catalog":
            return await _quest_catalog(ctx)
        if name == "read_quest":
            return await _read_quest(ctx, args)
        if name == "list_roles":
            return _list_roles(ctx)
        if name == "read_role":
            return _read_role(ctx, args)
        if name == "list_templates":
            return _list_templates(ctx)
        if name in RESEARCH_TOOLS:
            return await _research(ctx, name, args)
        if name == "kali_exec":
            return await _kali_exec(ctx, args)
        return f"error: unknown tool {name}"
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------- catalog

async def _quest_catalog(ctx: ToolCtx) -> str:
    rows = (await ctx.db.execute(
        select(Quest).where(Quest.active.is_(True))
        .order_by(Quest.track_slug, Quest.tier))).scalars().all()
    out = []
    for q in rows[:_MAX_LIST]:
        roles = sorted({r for v in (q.topology or {}).get("vms") or []
                        for r in v.get("roles") or []})
        out.append(f"{q.id} [{q.track_slug}/t{q.tier}] {q.title}"
                   f"{' (generated)' if q.generated else ''}"
                   + (f"\n    roles: {', '.join(roles)}" if roles else ""))
    return "\n".join(out) or "no quests synced"


async def _read_quest(ctx: ToolCtx, args: dict) -> str:
    q = await ctx.db.get(Quest, str(args.get("quest_id", "")))
    if not q:
        return "error: quest not found"
    root = Path(q.pack_path)
    # flag files live in flags/ per pack convention; allow basename lookups
    name = str(args.get("file", "")).strip().lstrip("/")
    for cand in (root / name, root / "flags" / name):
        if cand.is_file() and str(cand.resolve()).startswith(str(root)):
            return _read(cand)
    return (f"error: '{name}' not in pack. Try quest.yaml, briefing.md, "
            "coach_context.md, defense.md, cheatsheet.md")


def _list_roles(ctx: ToolCtx) -> str:
    base = _resolve_roles_dir(ctx)
    out = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        desc = ""
        meta = d / "meta" / "main.yml"
        if meta.is_file():
            for line in meta.read_text(errors="replace").splitlines():
                if "description:" in line:
                    desc = line.split("description:", 1)[1].strip()
                    break
        out.append(f"{d.name}  —  {desc}" if desc else d.name)
    return "\n".join(out[:_MAX_LIST]) or f"error: no roles under {base}"


def _read_role(ctx: ToolCtx, args: dict) -> str:
    base = _resolve_roles_dir(ctx)
    role = str(args.get("role", "")).strip()
    f = str(args.get("file", "")).strip().lstrip("/")
    p = _safe_under(base / role, f)
    if p is None:
        return ("error: not found. Try file='tasks/main.yml', "
                "'meta/main.yml', 'handlers/main.yml', or files/… paths")
    return _read(p)


def _list_templates(ctx: ToolCtx) -> str:
    base = _resolve_roles_dir(ctx)
    out = []
    for d in sorted(base.iterdir()):
        fdir = d / "files"
        if not fdir.is_dir():
            continue
        names = sorted(p.relative_to(fdir).parts[0]
                       for p in fdir.rglob("*") if p.is_file())
        if names:
            out.append(f"{d.name}: {', '.join(sorted(set(names))[:12])}")
    return "\n".join(out[:_MAX_LIST]) or "no files/ trees found"


# --------------------------------------------------------------- research

async def _research(ctx: ToolCtx, name: str, args: dict) -> str:
    if not ctx.web_enabled:
        return "denied: builder.web_enabled is off"
    if not researchkit.available():
        return "error: research modules unavailable (coach tree not mounted)"
    rc, web = researchkit.research_client(), researchkit.web_search_client()
    if name == "web_search":
        n = _int(args.get("max_results"), 8, 1, 20)
        return await web.search(str(args.get("query", "")), max_results=n)
    if name == "web_fetch":
        return await web.fetch(str(args.get("url", "")))
    if name == "query_vuln_db":
        return await rc.vulns(str(args.get("query", "")))
    if name == "rss_feed":
        return await rc.feed(str(args.get("feed", "list")),
                             count=_int(args.get("count"), 10, 1, 30))
    if name == "search_technique":
        return researchkit.grep_refs(str(args.get("query", "")))
    return f"error: unknown research tool {name}"


def _int(v, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------- verify

async def _kali_exec(ctx: ToolCtx, args: dict) -> str:
    if not ctx.verify_session_id:
        return "denied: kali_exec is only available during verification"
    cmd = str(args.get("command", "")).strip()
    if not cmd:
        return "error: empty command"
    if _is_denied(cmd):
        return "denied: matches the destructive-pattern blocklist"
    session = await ctx.db.get(Session, ctx.verify_session_id)
    if not session or not session.kali_vmid:
        return "error: verification session has no live Kali"
    if not getattr(ctx.engine, "pve", None):
        return "error: engine without guest-agent exec"
    res = await ctx.engine.pve.agent_exec_sh(
        session.kali_vmid, cmd,
        timeout_s=_int(args.get("timeout_s"), 120, 5, 600))
    out = (res.get("out") or "").strip()
    err = (res.get("err") or "").strip()
    code = res.get("exitcode")
    body = f"exit {code}"
    if out:
        body += f"\n{out[:8000]}"
    if err:
        body += f"\nstderr: {err[:2000]}"
    return body


def tools_for_phase(phase: str, *, has_verify: bool) -> list[dict]:
    """Catalog+research always; kali_exec only with a live verify session."""
    allow = CATALOG_TOOLS | RESEARCH_TOOLS
    if phase == "verify" and has_verify:
        allow |= VERIFY_TOOLS
    return [t for t in BUILDER_TOOLS
            if t["function"]["name"] in allow]
