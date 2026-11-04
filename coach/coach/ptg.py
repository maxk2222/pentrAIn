"""PTG — penetration task graph behind update_plan.

The tool surface stays `update_plan` (the model already knows it); items
may carry OPTIONAL structure — id, phase, deps, owner, done_when — turning
the flat checklist into a bounded DAG when the run needs coordination:

    {"t": "Enumerate web01:80", "s": "doing", "id": "p2",
     "ph": "enum", "deps": ["p1"], "ow": "w2",
     "dw": "endpoints + tech fingerprint", "at": 1}

Plain {t,s} items keep working — structure is opt-in per item, and
normalize is still atomic full-replace (a truncated rewrite can't leave
zombie steps). Dependency edges are validated: unknown refs dropped,
cycles broken, status coerced to the known set.
"""
from __future__ import annotations

MAX_TASKS = 16
TEXT_MAX = 110
_STATUS = {"done": "done", "complete": "done", "completed": "done",
           "x": "done", "finished": "done",
           "doing": "doing", "current": "doing", "wip": "doing",
           "active": "doing", "in_progress": "doing",
           "blocked": "blocked", "stuck": "blocked",
           "abandoned": "abandoned", "dropped": "abandoned",
           "skipped": "abandoned"}
OPEN = {"todo", "doing"}              # statuses a ready() task may carry
PHASES = {"recon", "enum", "web", "creds", "foothold", "privesc",
          "pivot", "loot", "verify", "report"}
MAX_ATTEMPTS = 3                      # spawns bound to one task


def _status(raw) -> str:
    return _STATUS.get(str(raw or "").strip().lower(), "todo")


def normalize_tasks(items) -> list[dict]:
    """LLM-supplied plan → bounded [{t,s, +optional id/ph/deps/ow/dw/at}].
    Bare strings count as todo; unknown statuses fall back to todo."""
    out: list[dict] = []
    for it in items or []:
        if len(out) >= MAX_TASKS:
            break
        if isinstance(it, str):
            t, s = it, "todo"
            it = {}
        elif isinstance(it, dict):
            t, s = (str(it.get("t") or it.get("text") or it.get("step")
                        or ""), _status(it.get("s") or it.get("status")))
        else:
            continue
        t = t.strip()[:TEXT_MAX]
        if not t:
            continue
        row: dict = {"t": t, "s": s}
        # optional PTG fields — only carried when present; a {t,s} plan
        # stays a {t,s} plan
        if it.get("id"):
            row["id"] = str(it["id"]).strip()[:16]
        if it.get("ph") or it.get("phase"):
            ph = str(it.get("ph") or it.get("phase")).strip().lower()[:12]
            row["ph"] = ph
        deps = it.get("deps")
        if isinstance(deps, list) and deps:
            row["deps"] = [str(d).strip()[:16] for d in deps[:6]]
        if it.get("ow") or it.get("owner"):
            row["ow"] = str(it.get("ow") or it.get("owner")).strip()[:12]
        if it.get("dw") or it.get("done_when"):
            row["dw"] = str(it.get("dw") or it.get("done_when")
                            ).strip()[:140]
        try:
            at = int(it.get("at") or 0)
            if at:
                row["at"] = at
        except (TypeError, ValueError):
            pass
        out.append(row)
    _fix_graph(out)
    return out


def _fix_graph(tasks: list[dict]) -> None:
    """Auto-assign ids when ANY task is structured (deps need them), drop
    deps referencing unknown ids, break cycles (first-encountered edge
    wins — the back-edge is removed)."""
    structured = any(set(t) - {"t", "s"} for t in tasks)
    if not structured:
        return
    seen: set[str] = set()
    for i, t in enumerate(tasks, 1):
        tid = t.get("id") or f"p{i}"
        while tid in seen:
            tid += "x"
        t["id"] = tid
        seen.add(tid)
    for t in tasks:
        deps = t.get("deps") or []
        t["deps"] = [d for d in deps if d in seen and d != t["id"]]
        if not t["deps"]:
            t.pop("deps", None)
    # DFS cycle-break — build adjacency, drop edges that close a cycle
    graph = {t["id"]: set(t.get("deps") or []) for t in tasks}
    for tid, deps in graph.items():
        # can tid reach itself through deps? then cut the offending edge
        stack, visited = list(deps), set()
        while stack:
            cur = stack.pop()
            if cur == tid:
                # find and remove one edge that closes the loop — the dep
                # on the path head is the simplest cut
                for d in list(deps):
                    if _reaches(d, tid, graph, set()):
                        deps.discard(d)
                        break
                break
            if cur in visited:
                continue
            visited.add(cur)
            stack.extend(graph.get(cur) or ())
    for t in tasks:
        deps = sorted(graph.get(t["id"]) or ())
        if deps:
            t["deps"] = deps
        else:
            t.pop("deps", None)


def _reaches(src: str, dst: str, graph: dict, visited: set) -> bool:
    if src == dst:
        return True
    if src in visited:
        return False
    visited.add(src)
    return any(_reaches(d, dst, graph, visited)
               for d in (graph.get(src) or ()))


def ready(tasks: list[dict]) -> list[dict]:
    """Open tasks whose deps are ALL done — the deterministic work queue.
    Unstructured items (no id) are always ready."""
    done_ids = {t["id"] for t in tasks if t.get("s") == "done" and t.get("id")}
    out = []
    for t in tasks:
        if t.get("s") not in OPEN:
            continue
        if t.get("id") and not set(t.get("deps") or ()) <= done_ids:
            continue
        out.append(t)
    return out


def by_id(tasks: list[dict], tid: str) -> dict | None:
    return next((t for t in tasks if t.get("id") == tid), None)


def mark(tasks: list[dict], tid: str, status: str) -> dict | None:
    """Worker-bound status transitions — done when it reported, blocked
    when it died. Returns the task or None."""
    t = by_id(tasks, tid)
    if t is not None:
        t["s"] = _status(status)
    return t
