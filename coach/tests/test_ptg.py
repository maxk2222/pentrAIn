"""PTG — structured plan items behind update_plan: normalize, deps,
cycles, ready-queue, worker binding, and the attempts guard."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.loop import SessionCoach
from coach.ptg import MAX_ATTEMPTS, by_id, mark, normalize_tasks, ready
from coach.state import normalize_plan


def test_plain_items_stay_flat():
    out = normalize_tasks(["recon", {"t": "enum", "s": "doing"}])
    assert out == [{"t": "recon", "s": "todo"},
                   {"t": "enum", "s": "doing"}]


def test_structured_items_get_ids_and_statuses():
    out = normalize_tasks([
        {"t": "recon lan", "id": "p1", "ph": "recon", "s": "done"},
        {"t": "enum web", "ph": "web", "deps": ["p1"], "dw": "endpoints"},
        {"t": "x", "s": "in_progress"},   # status alias → doing
        {"t": "y", "s": "bogus"},         # unknown → todo
    ])
    assert [t["id"] for t in out] == ["p1", "p2", "p3", "p4"]
    assert out[1]["deps"] == ["p1"] and out[1]["dw"] == "endpoints"
    assert out[2]["s"] == "doing" and out[3]["s"] == "todo"


def test_unknown_and_self_deps_dropped():
    out = normalize_tasks([
        {"t": "a", "deps": ["nope", "p1"]},   # p1=self → dropped too
    ])
    assert "deps" not in out[0]


def test_cycle_edges_broken():
    out = normalize_tasks([
        {"t": "a", "deps": ["p3"]},
        {"t": "b"},
        {"t": "c", "deps": ["p1"]},
    ])
    # p1<-p3<-p1 cycle: the closing edge must be cut so ready() can't stall
    rdy = ready(out)
    assert rdy, "cycle left every task blocked forever"


def test_ready_queue_respects_deps():
    out = normalize_tasks([
        {"t": "recon", "id": "p1", "s": "done"},
        {"t": "enum", "deps": ["p1"]},
        {"t": "exploit", "deps": ["p2"]},
        {"t": "report"},
    ])
    rdy = [t["t"] for t in ready(out)]
    assert rdy == ["enum", "report"]      # exploit waits on p2


def test_blocked_and_abandoned_not_ready():
    out = normalize_tasks([
        {"t": "a", "s": "blocked"}, {"t": "b", "s": "abandoned"},
        {"t": "c"}])
    assert [t["t"] for t in ready(out)] == ["c"]


def test_normalize_plan_keeps_structured_keys():
    out = normalize_plan([{"t": "x", "id": "p1", "ow": "w2", "ph": "web"}])
    assert out[0]["id"] == "p1" and out[0]["ow"] == "w2"


def test_mark_transitions():
    # ids only exist on structured items — unstructured tasks are
    # unbindable by design (spawn_agent errors on unknown ids)
    tasks = normalize_tasks([{"t": "a", "ph": "recon"}])
    assert mark(tasks, "p1", "done")["s"] == "done"
    assert mark(tasks, "nope", "done") is None


# ---------- spawn_agent PTG binding (loop-level) ----------

class _FakeClient:
    def __init__(self):
        self.ctx = {
            "session": {"id": 1, "state": "active", "autonomy_level": 4,
                        "coach_enabled": True, "subagents_enabled": True},
            "quest": {"title": "Q", "track": "net", "tier": 1,
                      "briefing": "b", "coach_context": "", "checkpoints": [],
                      "escalation": {},
                      "targets": [{"name": "nas", "ip": "192.168.3.55"}]},
            "flags": [], "checkpoints_hit": [], "telemetry_tail": [],
            "messages": [], "exec_count": 0,
            "profile": {"track_levels": {"net": 1}},
        }

    async def send_chat(self, *a, **k): return {}
    async def session_context(self, sid): return self.ctx
    async def log_action(self, *a, **k): return {}
    async def stream_draft(self, *a, **k): pass
    async def send_activity(self, *a, **k): pass
    async def send_agents(self, *a, **k): pass
    async def exec_in_kali(self, *a, **k):
        return {"out": "ok", "exitcode": 0, "visible": True}
    async def report_llm_usage(self, *a, **k): return {}


def _coach():
    return SessionCoach(1, _FakeClient(),
                        {"coach": {"max_workers": 4}, "llm": {}})


def _stall_llm():
    return type("L", (), {"chat": staticmethod(
        lambda *a, **k: asyncio.sleep(60)), "model": "fake"})()


async def test_spawn_binds_task_and_finish_marks_it():
    coach = _coach()
    await coach.start()
    coach.llm = _stall_llm()
    coach.state.plan = normalize_tasks([
        {"t": "enum web", "id": "p2", "ph": "web"}])
    _v, r = await coach._dispatch(
        {"type": "spawn_agent", "task": "x", "task_id": "p2"})
    assert "spawned w1" in r
    t = by_id(coach.state.plan, "p2")
    assert t["s"] == "doing" and t["ow"] == "w1" and t["at"] == 1
    # a second bind while owned is denied
    _v, r = await coach._dispatch(
        {"type": "spawn_agent", "task": "y", "task_id": "p2"})
    assert r.startswith("denied: task p2 is already owned")
    # kill the worker → task settles blocked (not done)
    await coach._dispatch({"type": "kill_agent", "worker_id": "w1"})
    await asyncio.sleep(0)   # _finish_worker runs inside the cancelled task
    assert by_id(coach.state.plan, "p2")["s"] in ("blocked", "doing")
    await coach.stop()


async def test_spawn_unknown_task_id_errors():
    coach = _coach()
    await coach.start()
    coach.llm = _stall_llm()
    _v, r = await coach._dispatch(
        {"type": "spawn_agent", "task": "x", "task_id": "zz"})
    assert r.startswith("error: no plan task")
    await coach.stop()


async def test_spawn_attempts_cap():
    coach = _coach()
    await coach.start()
    coach.llm = _stall_llm()
    coach.state.plan = normalize_tasks([{"t": "t", "id": "p1"}])
    coach.state.plan[0]["at"] = MAX_ATTEMPTS
    _v, r = await coach._dispatch(
        {"type": "spawn_agent", "task": "x", "task_id": "p1"})
    assert r.startswith("denied: task p1 already consumed")
    await coach.stop()
