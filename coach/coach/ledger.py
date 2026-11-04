"""Coverage ledger + shared notes pad — agent-owned engagement bookkeeping.

FactsDB says what IS (deterministically extracted from output); the ledger
says what WAS COVERED (agent-declared testing outcomes per surface) and the
notes pad carries cross-agent curated context (cred inventories, endpoint
lists, rate-limit quirks) that deterministically parsed facts can't hold.

Both are session-scoped, bounded, and survive restarts the same way the plan
does: writer tools log via coach_actions, session_context pulls the log back
into ctx, and the coach replays it on attach — apply(tool, args) is the
replay entry point.
"""
from __future__ import annotations

import re
import time

MAX_SURFACES = 48
MAX_NOTES = 24
_EVIDENCE_MAX = 200
_TEXT_MAX = 240

# coverage outcome vocabulary — Strix-style closure discipline: every
# opened surface ends in exactly one state, "moved on" is not a state
OUTCOMES = {"untested", "testing", "tested_clean", "open_gap",
            "confirmed", "needs_follow_up"}
_OUTCOME_ALIAS = {
    "clean": "tested_clean", "ruled_out": "tested_clean",
    "ruled-out": "tested_clean", "closed": "tested_clean",
    "gap": "open_gap", "open": "needs_follow_up",
    "follow_up": "needs_follow_up", "vuln": "confirmed",
    "done": "confirmed", "wip": "testing", "todo": "untested",
}

_IP_PORT = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?$")


def surface_key(surface: str) -> str:
    """Canonical surface key so '10.0.0.5:80', 'http://10.0.0.5:80/' and
    ' 10.0.0.5:80 ' dedupe to one row. Non-ip surfaces (paths, cred-vecs,
    'host|user') keep their literal shape — trimmed and single-spaced."""
    s = " ".join(str(surface or "").strip().split())
    s = re.sub(r"^https?://", "", s).rstrip("/")
    m = _IP_PORT.match(s)
    if m and m.group(2):
        return f"{m.group(1)}:{m.group(2)}"
    return s[:120]


class CoverageLedger:
    """One row per attack surface — the answer to 'have we already tried X'
    that the anti-loop guards can't give (they only catch exact repeats)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}   # key -> row
        self._order: list[str] = []       # insertion order for bounding

    def record(self, surface: str, area: str = "", outcome: str = "testing",
               evidence: str = "", owner: str = "main") -> dict:
        key = surface_key(surface)
        if not key:
            return {"error": "empty surface"}
        outcome = _OUTCOME_ALIAS.get(str(outcome).strip().lower(),
                                     str(outcome).strip().lower())
        if outcome not in OUTCOMES:
            return {"error": f"bad outcome — one of {sorted(OUTCOMES)}"}
        row = self.rows.get(key)
        verb = "updated"
        if row is None:
            row = {"surface": key, "area": str(area or "")[:40],
                   "outcome": outcome, "evidence": str(evidence or "")[:_EVIDENCE_MAX],
                   "owner": str(owner or "main")[:16], "ts": time.time()}
            self.rows[key] = row
            self._order.append(key)
            verb = "recorded"
            if len(self._order) > MAX_SURFACES:
                # evict the oldest UNRESOLVED row first — a confirmed/open_gap
                # row is proof of work, an untested one is a stale lead
                for k in self._order:
                    if self.rows[k]["outcome"] in ("untested", "testing"):
                        self._order.remove(k)
                        self.rows.pop(k, None)
                        break
                else:
                    k = self._order.pop(0)
                    self.rows.pop(k, None)
        else:
            row["outcome"] = outcome
            if area:
                row["area"] = str(area)[:40]
            if evidence:
                row["evidence"] = str(evidence)[:_EVIDENCE_MAX]
            row["owner"] = str(owner or row["owner"])[:16]
            row["ts"] = time.time()
        return {"ok": verb, "surface": key, "outcome": outcome}

    def update(self, surface: str, outcome: str, evidence: str = "",
               owner: str = "") -> dict:
        key = surface_key(surface)
        if key not in self.rows:
            return {"error": f"no row for {key!r} — record it first"}
        return self.record(key, "", outcome, evidence, owner or
                           self.rows[key]["owner"])

    def get(self, surface: str) -> dict | None:
        return self.rows.get(surface_key(surface))

    def open_followups(self) -> list[dict]:
        return [self.rows[k] for k in self._order
                if self.rows[k]["outcome"] == "needs_follow_up"]

    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for r in self.rows.values():
            c[r["outcome"]] = c.get(r["outcome"], 0) + 1
        return c

    # replay: apply a logged writer action in order — same merge semantics
    # live dispatch uses, so a rebuild ends in the identical end-state
    def apply(self, tool: str, args: dict) -> None:
        if tool == "update_coverage":
            self.update(args.get("surface"), args.get("outcome") or "testing",
                        args.get("evidence") or "", args.get("agent") or "main")
        elif tool == "record_coverage":
            self.record(args.get("surface"), args.get("area") or "",
                        args.get("outcome") or "testing",
                        args.get("evidence") or "", args.get("agent") or "main")

    def render(self, max_chars: int = 320) -> str:
        """Compact COVERAGE: block — unresolved work first, then proof rows.
        Bounded like FACTS: the render is context, not the store."""
        if not self.rows:
            return ""
        rank = {"needs_follow_up": 0, "open_gap": 1, "testing": 2,
                "confirmed": 3, "untested": 4, "tested_clean": 5}
        keys = sorted(self._order, key=lambda k: rank[self.rows[k]["outcome"]])
        lines = []
        for k in keys[:10]:
            r = self.rows[k]
            tag = r["outcome"].replace("_", "-")
            own = f"@{r['owner']}" if r["owner"] != "main" else ""
            ev = f" — {r['evidence'][:60]}" if r["evidence"] else ""
            area = f" [{r['area']}]" if r["area"] else ""
            lines.append(f" {r['surface']}{area} → {tag}{own}{ev}")
        if len(keys) > 10:
            lines.append(f" +{len(keys) - 10} more")
        out = "COVERAGE:\n" + "\n".join(lines)
        return out[:max_chars]


class NotesPad:
    """Shared scratchpad — durable cross-agent context that isn't a finding
    and isn't coverage: working cred sets, endpoint inventories, quirks.
    Agent-written (FactsDB is extracted); every worker sees it at spawn."""

    def __init__(self) -> None:
        self.notes: dict[str, dict] = {}
        self._order: list[str] = []

    def create(self, key: str, text: str, owner: str = "main") -> dict:
        k = " ".join(str(key or "").strip().split())[:48]
        t = str(text or "").strip()[:_TEXT_MAX]
        if not k or not t:
            return {"error": "need key + text"}
        if k in self.notes:
            self.notes[k].update(text=t, owner=owner or self.notes[k]["owner"],
                                 ts=time.time())
            return {"ok": "updated", "key": k}
        self.notes[k] = {"key": k, "text": t,
                         "owner": str(owner or "main")[:16], "ts": time.time()}
        self._order.append(k)
        if len(self._order) > MAX_NOTES:
            old = self._order.pop(0)
            self.notes.pop(old, None)
        return {"ok": "created", "key": k}

    def apply(self, tool: str, args: dict) -> None:
        if tool == "create_note":
            self.create(args.get("key"), args.get("text") or
                        args.get("content") or "", args.get("agent") or "main")

    def render(self, max_chars: int = 320) -> str:
        if not self.notes:
            return ""
        lines = []
        for k in self._order[-8:]:
            n = self.notes[k]
            own = f" @{n['owner']}" if n["owner"] != "main" else ""
            lines.append(f" {n['key']}{own}: {n['text'][:110]}")
        return "SHARED_NOTES:\n" + "\n".join(lines)
