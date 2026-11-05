"""Builder research — reuse the coach's standalone research modules.

coach/websearch.py (SSRF-safe fetch + key-free search) and
coach/research.py (NVD/KEV + curated feeds + technique refs) import only
httpx + stdlib — this shim puts the coach source tree on sys.path instead
of duplicating ~700 lines of security-sensitive code. In the container the
tree arrives via the read-only ../coach:/coach-src mount; in dev it's the
repo checkout. If neither resolves, every helper degrades to an honest
`error:` result instead of an import crash.

trafilatura is optional inside websearch — the regex fallback applies here.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]          # backend/app/services → repo root


def _ensure_coach_path() -> bool:
    from ..config import get_config
    cands = [Path(get_config().coach_src_dir), Path("/coach-src"),
             _REPO / "coach"]
    for cand in cands:
        if (cand / "coach" / "websearch.py").exists():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            return True
    return False


try:
    _ok = _ensure_coach_path()
    from coach.research import FEEDS, TECHNIQUE_SITES, ResearchClient, ResearchError, grep_refs
    from coach.websearch import WebError, WebSearch
except Exception:                                      # pragma: no cover
    _ok = False
    FEEDS, TECHNIQUE_SITES = {}, {}
    ResearchClient = WebSearch = None                  # type: ignore[assignment]
    ResearchError = WebError = Exception               # type: ignore[assignment]

    def grep_refs(query: str, **kw) -> str:            # type: ignore[misc]
        return "error: research modules unavailable (coach tree not mounted)"


def available() -> bool:
    return _ok


def web_search_client() -> WebSearch:
    """Shared fetch/search client — module-level so its caches persist."""
    global _web
    try:
        return _web
    except NameError:
        _web = WebSearch() if _ok else None
        return _web


def research_client() -> ResearchClient:
    global _rc
    try:
        return _rc
    except NameError:
        _rc = ResearchClient() if _ok else None
        return _rc
