"""Engagement findings + report assembly — backend view of the agent's
typed findings. The coach persists every record_finding call as a
CoachAction row; replaying those rows (same dedup/update semantics as
FactsDB.apply_finding) yields the current finding set without needing the
live coach process. Powers GET /sessions/{id}/findings|report and the
frontend findings panel.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.domain import CoachAction, Session

# mirrors coach/coach/facts.py _VULN_STATUS — keep the two in sync: the
# coach is authoritative at runtime, this is the persisted-ops view
_STATUS = {
    "hypothesis": "candidate", "candidate": "candidate",
    "suspected": "candidate", "possible": "candidate",
    "confirmed": "confirmed", "validated": "confirmed",
    "proven": "confirmed", "verified": "confirmed",
    "rejected": "rejected", "false-positive": "rejected",
    "false_positive": "rejected", "dead": "rejected",
}
_SEV = {"info", "low", "medium", "high", "critical"}


def _norm_status(raw) -> str:
    return _STATUS.get(str(raw or "").strip().lower(), "candidate")


async def findings(db: AsyncSession, session_id: int) -> list[dict]:
    """Replay record_finding rows → current finding set (latest write wins
    per id, title+host dedup on creates, confirmed needs ≥12ch evidence —
    the same gates FactsDB applies live)."""
    rows = (await db.execute(
        select(CoachAction.args).where(
            CoachAction.session_id == session_id,
            CoachAction.tool == "record_finding")
        .order_by(CoachAction.id))).scalars().all()
    out: dict[str, dict] = {}
    seq = 0
    for raw in rows:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                continue
        if not isinstance(raw, dict):
            continue
        vid = str(raw.get("id") or "").strip()
        if vid and vid in out:                       # validation update
            row = out[vid]
            for k in ("status", "evidence", "next", "title", "host"):
                if raw.get(k) not in (None, ""):
                    row[k] = str(raw[k])[:200]
            sev = str(raw.get("sev") or "").lower()
            if sev in _SEV:
                row["sev"] = sev
            row["status"] = _norm_status(row["status"])
            if row["status"] == "confirmed" and len(row["evidence"]) < 12:
                row["status"] = "candidate"
            continue
        if vid:                                      # update to unknown id
            continue
        title = str(raw.get("title") or "")[:100]
        host = str(raw.get("host") or "")[:60]
        if not title:
            continue
        status = _norm_status(raw.get("status"))
        ev = str(raw.get("evidence") or "")[:200]
        if status == "confirmed" and len(ev) < 12:
            status = "candidate"
        rec = {"title": title, "host": host, "status": status,
               "sev": (str(raw.get("sev") or "info").lower()
                       if str(raw.get("sev") or "").lower() in _SEV
                       else "info"),
               "evidence": ev,
               "next": str(raw.get("next") or "")[:120],
               "owner": str(raw.get("agent") or "main")[:12]}
        old = next((v for v in out.values()
                    if v["title"] == title and v["host"] == host), None)
        if old is not None:
            _sev_ord = {s: i for i, s in enumerate(
                ["info", "low", "medium", "high", "critical"])}
            new_sev = rec.pop("sev")
            old.update({k: v for k, v in rec.items() if v != ""})
            # dedup-merge keeps the STRONGER severity (mirror of
            # FactsDB._merge_vuln — explicit downgrades go via id-update)
            if _sev_ord.get(new_sev, 0) > _sev_ord.get(old["sev"], 0):
                old["sev"] = new_sev
            continue
        seq += 1
        rec["id"] = f"v{seq}"
        out[rec["id"]] = rec
    return list(out.values())


def _row_surface(args) -> tuple[str, str, str]:
    """(surface, outcome, evidence) from a coverage writer row."""
    return (str(args.get("surface") or "")[:80],
            str(args.get("outcome") or "")[:20],
            str(args.get("evidence") or "")[:160])


async def coverage(db: AsyncSession, session_id: int) -> dict[str, dict]:
    """Replay record/update_coverage rows → current ledger state."""
    rows = (await db.execute(
        select(CoachAction.tool, CoachAction.args).where(
            CoachAction.session_id == session_id,
            CoachAction.tool.in_(["record_coverage", "update_coverage"]))
        .order_by(CoachAction.id))).all()
    out: dict[str, dict] = {}
    for tool, raw in rows:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                continue
        if not isinstance(raw, dict):
            continue
        surface, outcome, evidence = _row_surface(raw)
        if not surface:
            continue
        if tool == "update_coverage" and surface not in out:
            continue                                 # update before record
        row = out.setdefault(surface, {"surface": surface})
        row["outcome"] = outcome
        if evidence:
            row["evidence"] = evidence
    return out


def report_md(session: Session, finds: list[dict],
              cov: dict[str, dict]) -> str:
    """Full markdown report — same grouping the coach's build_report tool
    emits, without its size cap (this is the complete deliverable)."""
    scope = {}
    if session.scope_json:
        try:
            scope = json.loads(session.scope_json)
        except (TypeError, ValueError):
            scope = {}
    L = ["# Penetration Test Report", ""]
    if scope.get("locked"):
        L += [f"**Authorized scope** ({scope.get('authorized_by', '?')} — "
              f"{scope.get('authorized_at', '')}): "
              f"{', '.join(scope.get('nets') or [])}"
              + (f" | hosts: {', '.join(scope.get('hosts') or [])}"
                 if scope.get("hosts") else "")
              + (f" | ports: {scope.get('ports')}" if scope.get("ports")
                 else ""), ""]
    conf = [v for v in finds if v["status"] == "confirmed"]
    cand = [v for v in finds if v["status"] == "candidate"]
    rej = [v for v in finds if v["status"] == "rejected"]
    L += ["## Findings", ""]
    if conf:
        for v in conf:
            L.append(f"### [{v['id']}] {v['title']} — {v['sev'].upper()}"
                     + (f" on {v['host']}" if v["host"] else ""))
            if v["evidence"]:
                L.append(f"- Evidence: {v['evidence']}")
            if v["next"]:
                L.append(f"- Next/remediation: {v['next']}")
            L.append("")
    else:
        L += ["No confirmed findings.", ""]
    if cand:
        L += ["## Candidates (unvalidated)", ""]
        L += [f"- [{v['id']}] {v['title']}"
              + (f" on {v['host']}" if v["host"] else "")
              + (f" — {v['evidence'][:80]}" if v["evidence"] else "")
              for v in cand]
        L.append("")
    if rej:
        L += ["## Tested & ruled out", ""]
        L += [f"- {v['title']}" + (f" on {v['host']}" if v["host"] else "")
              for v in rej]
        L.append("")
    if cov:
        open_rows = [r for r in cov.values()
                     if r.get("outcome") in ("untested", "testing")]
        L += [f"## Coverage — {len(cov)} surfaces, {len(open_rows)} open",
              ""]
        L += [f"- {r['surface']} → {r.get('outcome', '?')}"
              + (f" — {r['evidence'][:80]}" if r.get("evidence") else "")
              for r in list(cov.values())[:40]]
        L.append("")
    return "\n".join(L)
