"""Technique recipe modules — the coach's consultable knowledge base.

The monolithic kali-environment.md holds only always-on environment facts
(tools, topology, shell quirks, discipline). Detailed technique recipes —
verbatim commands, ordered procedures — live as separate modules under
knowledge/modules/<id>.md so the prompt stays small and the model pulls
the recipe it needs via the lookup_guide tool instead of carrying ~18K
of mostly-irrelevant text every turn.

Module format (front-matter + body):

    ---
    id: git-leak
    title: Exposed .git → object-walk extraction
    triggers: [.git/, git/logs, git-dumper]
    ---
    <markdown body — verbatim command snippets welcome>

`triggers` are substring keywords matched against command+output text by
triggers_for() — deterministic hints appended to tool results so a weak
model does not have to know what to search for ("GUIDE: module 'x' covers
this"). Keep triggers specific: better one hint too few than spam.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_MODULES_DIR = Path(__file__).parent / "knowledge" / "modules"

_HEADER = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV = re.compile(r"^(\w[\w-]*)\s*:\s*(.*)$")
_LIST = re.compile(r"\[(.*)\]")


@dataclass
class Module:
    id: str
    title: str = ""
    triggers: list[str] = field(default_factory=list)
    body: str = ""


def _parse(path: Path) -> Module | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    m = _HEADER.match(text)
    if not m:
        # no front-matter — the filename is the id, whole file is the body
        return Module(id=path.stem, title=path.stem, body=text.strip())
    meta: dict[str, str] = {}
    for ln in m.group(1).splitlines():
        kv = _KV.match(ln.strip())
        if kv:
            meta[kv.group(1).lower()] = kv.group(2).strip()
    triggers_raw = meta.get("triggers", "")
    lm = _LIST.search(triggers_raw)
    triggers = ([t.strip().strip("\"'") for t in lm.group(1).split(",")]
                if lm else
                [t.strip() for t in triggers_raw.split(",") if t.strip()])
    return Module(
        id=meta.get("id") or path.stem,
        title=meta.get("title") or path.stem,
        triggers=[t for t in triggers if t],
        body=text[m.end():].strip())


_cache: dict[str, Module] | None = None


def load_modules(*, reload: bool = False) -> dict[str, Module]:
    """All modules keyed by id — cached; files are deploy-static."""
    global _cache
    if _cache is None or reload:
        _cache = {}
        try:
            files = sorted(f for f in _MODULES_DIR.glob("*.md")
                           if not f.name.startswith("._"))
        except OSError:
            files = []
        for p in files:
            mod = _parse(p)
            if mod:
                _cache[mod.id] = mod
        if not _cache:
            log.debug("no knowledge modules found", dir=str(_MODULES_DIR))
    return _cache


def index(cap: int = 2000) -> str:
    """One line per module for the system prompt — the model must know the
    modules exist to look them up; the bodies stay out of the prompt."""
    lines = [f"{m.id} — {m.title}" for m in load_modules().values()]
    return "\n".join(lines)[:cap]


def _resolve(query: str) -> tuple[Module | None, list[Module]]:
    """Shared resolution: (winning module | None, scored candidates).
    None also on ambiguity — callers that need a definite id must not
    guess among equals."""
    q = (query or "").strip().lower()
    mods = load_modules()
    if not q or not mods:
        return None, []
    if q in mods:
        return mods[q], []
    scored: list[tuple[int, Module]] = []
    for m in mods.values():
        score = 0
        if q in m.id.lower():
            score += 4
        if q in m.title.lower():
            score += 3
        if any(q in t.lower() or t.lower() in q for t in m.triggers):
            score += 2
        if q in m.body.lower():
            score += 1
        if score:
            scored.append((score, m))
    if not scored:
        return None, []
    scored.sort(key=lambda sm: -sm[0])
    if len(scored) == 1 or scored[0][0] > scored[1][0]:
        return scored[0][1], [m for _s, m in scored]
    return None, [m for _s, m in scored]


def resolve_id(query: str) -> str | None:
    """The module id lookup() would return — None on miss/ambiguity.
    Lets callers dedupe fetches by module id rather than raw query
    (`git objects` and `.git extraction` resolve to the same module)."""
    m, _ = _resolve(query)
    return m.id if m else None


def lookup(query: str, cap: int = 1900) -> str:
    """id exact match → title/trigger substring → body substring.
    Returns the module body (capped), a short candidate list on multiple
    matches, or an error naming the known ids."""
    q = (query or "").strip().lower()
    if not load_modules():
        return "error: knowledge base empty"
    if not q:
        return ("error: empty query — known guides:\n" + index(1500))
    m, cands = _resolve(q)
    if m:
        return f"# {m.title}\n\n{m.body}"[:cap]
    if not cands:
        return (f"error: unknown guide {query!r} — known guides:\n"
                + index(1500))
    # ambiguous — name the candidates rather than guessing
    named = " | ".join(f"{m.id} — {m.title}" for m in cands[:4])
    return (f"multiple guides match {query!r}: {named} — "
            "call lookup_guide again with the exact id")


# role → knowledge modules pre-inlined into the worker spawn prompt —
# the common-case recipes for that specialty, so the worker does not
# have to discover them via lookup_guide mid-task (Strix preload
# pattern). Keep it short: workers have ~80 turns, every loaded byte is
# prompt tax on a narrow task. Empty list = pull via lookup_guide.
ROLE_MODULES: dict[str, list[str]] = {
    "recon":   ["minimal-hosts"],
    "web":     ["web-app", "ssrf-lfi", "sqli-basic"],
    "creds":   [],
    "svc":     ["minimal-hosts", "log-parsing"],
    "privesc": ["privesc-linux", "privesc-cron", "privesc-win"],
    "pivot":   ["pivoting", "nested-rce"],
    "verify":  [],
    "general": [],
}


def preload_for(role: str, *, max_mods: int = 3, cap_per: int = 1100,
                cap_total: int = 3200) -> str:
    """Recipe bodies for the given worker role — pre-rendered so the
    spawn prompt can carry them directly. Unknown/empty role → ''."""
    mods = load_modules()
    parts: list[str] = []
    for mid in ROLE_MODULES.get(role or "", [])[:max_mods]:
        m = mods.get(mid)
        if m:
            parts.append(f"### {m.title}\n{m.body[:cap_per]}")
    return "\n\n".join(parts)[:cap_total]


def _trigger_re(trigger: str) -> re.Pattern:
    """Trigger → regex. Word edges get \\b anchors so 'pod' can't fire on
    'tripod'; triggers with non-word edges (like '.git/' or '?c=') are
    already self-delimiting and match literally."""
    pat = re.escape(trigger.lower())
    if trigger[:1].isalnum():
        pat = r"\b" + pat
    if trigger[-1:].isalnum():
        pat = pat + r"\b"
    return re.compile(pat)


def triggers_for(text: str) -> list[str]:
    """Module ids whose trigger keywords appear in command/output text —
    for deterministic 'module X covers this' hints on the guaranteed-read
    channel. Ordered, deduped."""
    if not text:
        return []
    low = text.lower()
    hits: list[str] = []
    for m in load_modules().values():
        if any(len(t) >= 3 and _trigger_re(t).search(low)
               for t in m.triggers):
            hits.append(m.id)
    return hits
