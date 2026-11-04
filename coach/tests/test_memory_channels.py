"""P2 memory tools + P3 channels — dispatch-level tests with a fake
backend client: threat_model persistence fields, search/record/
play_outcome flows, channel lifecycle and scope guards."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.loop import SessionCoach


class FakeClient:
    def __init__(self, scope=None):
        self.plays = []
        self.searches = []
        self.feedback = []
        self.typed = []
        self.peeked = []
        self.ctx = {
            "session": {"id": 1, "state": "active", "autonomy_level": 4,
                        "coach_enabled": True, "subagents_enabled": True},
            "session_tools": "nmap curl",
            "quest": {"title": "Eng", "track": "net", "tier": 1,
                      "briefing": "b", "coach_context": "", "checkpoints": [],
                      "escalation": {},
                      "targets": [{"name": "app01", "ip": "10.1.10.21"}]},
            "flags": [], "checkpoints_hit": [], "telemetry_tail": [],
            "messages": [], "exec_count": 0,
            "profile": {"track_levels": {"net": 1}},
        }
        if scope is not None:
            self.ctx["scope"] = scope

    async def send_chat(self, *a, **k): return {}
    async def session_context(self, sid): return self.ctx
    async def log_action(self, *a, **k): return {}
    async def log_denial(self, *a, **k): return {}
    async def stream_draft(self, *a, **k): pass
    async def send_activity(self, *a, **k): pass
    async def send_agents(self, *a, **k): pass
    async def report_llm_usage(self, *a, **k): return {}
    async def exec_in_kali(self, *a, **k):
        return {"out": "ok", "exitcode": 0, "visible": True}
    async def type_in_pane(self, sid, text, window=None):
        self.typed.append((window, text))
        return {"out": f"pane tail for {text}", "current_command": "ssh",
                "busy": True}
    async def peek_pane(self, sid, window):
        self.peeked.append(window)
        return {"out": "chan tail", "current_command": "ssh", "busy": True}
    async def search_memory(self, sid, q):
        self.searches.append(q)
        return {"hits": [
            {"id": 7, "title": "wp creds → theme shell → suid",
             "confidence": 0.6, "tags": ["wordpress"],
             "steps": ["enum: wpscan finds admin",
                       "shell: theme editor upload",
                       "root: suid env /bin/sh"],
             "outcome": "root"}]}
    async def record_play(self, sid, title, tags, steps, outcome="",
                          applies="global"):
        self.plays.append({"title": title, "tags": tags, "steps": steps})
        return {"id": 42}
    async def play_feedback(self, pid, ok):
        self.feedback.append((pid, ok))
        return {}


class FakeLlm:
    model = "fake"

    async def chat(self, *a, **k):
        return {"content": "", "actions": [{"type": "none"}],
                "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}


async def _coach(scope=None):
    c = FakeClient(scope)
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start()
    return coach, c


async def _d(coach, a):
    _v, r = await coach._dispatch(a)
    return r


# ---------- threat_model ----------

async def test_threat_model_set_and_amend():
    coach, _ = await _coach()
    r = await _d(coach, {"type": "threat_model",
                         "attacker": "external unauth",
                         "assets": "customer db"})
    assert "external unauth" in r
    assert coach.state.threat_model["attacker"] == "external unauth"
    # amend one field keeps the others
    await _d(coach, {"type": "threat_model",
                     "boundaries": "dmz→lan"})
    tm = coach.state.threat_model
    assert tm["attacker"] == "external unauth" and tm["assets"] == "customer db"
    assert tm["boundaries"] == "dmz→lan"
    await coach.stop()


async def test_threat_model_empty_rejected():
    coach, _ = await _coach()
    r = await _d(coach, {"type": "threat_model"})
    assert r.startswith("error:")
    await coach.stop()


# ---------- memory tools ----------

async def test_search_memory_renders_hits():
    coach, c = await _coach()
    r = await _d(coach, {"type": "search_memory",
                         "query": "wordpress foothold"})
    assert "ap7" in r and "theme shell" in r and "play_outcome" in r
    assert c.searches == ["wordpress foothold"]
    await coach.stop()


async def test_search_memory_empty():
    coach, c = await _coach()

    async def no_hits(sid, q): return {"hits": []}
    c.search_memory = no_hits
    r = await _d(coach, {"type": "search_memory", "query": "obscure"})
    assert "no memory hits" in r
    await coach.stop()


async def test_record_play_and_feedback():
    coach, c = await _coach()
    r = await _d(coach, {"type": "record_play",
                         "title": "x → y → root",
                         "tags": ["ssh"], "steps": ["a", "b"],
                         "outcome": "root"})
    assert "ap42" in r
    assert c.plays[0]["title"] == "x → y → root"
    r = await _d(coach, {"type": "play_outcome", "play_id": 42, "ok": False})
    assert "stale" in r
    import asyncio
    await asyncio.sleep(0.05)          # play_feedback is fire-and-forget
    assert c.feedback == [(42, False)]
    await coach.stop()


async def test_play_outcome_bad_id_no_crash():
    """int() on a non-numeric play_id must not kill the turn."""
    coach, _ = await _coach()
    r = await _d(coach, {"type": "play_outcome",
                         "play_id": "abc", "ok": True})
    assert r.startswith("error:")
    await coach.stop()


# ---------- channels ----------

async def test_channel_lifecycle():
    coach, c = await _coach()
    r = await _d(coach, {"type": "channel_open", "channel": "s1",
                         "command": "ssh user@10.1.10.21"})
    assert "channel s1 open" in r and "c-s1" in r
    assert c.typed[-1] == ("c-s1", "ssh user@10.1.10.21")
    r = await _d(coach, {"type": "channel_send", "channel": "s1",
                         "text": "id"})
    assert "[s1]" in r
    assert c.typed[-1] == ("c-s1", "id")
    r = await _d(coach, {"type": "channel_read", "channel": "s1"})
    assert "chan tail" in r and c.peeked[-1] == "c-s1"
    r = await _d(coach, {"type": "channel_close", "channel": "s1"})
    assert "closed" in r
    r = await _d(coach, {"type": "channel_read", "channel": "s1"})
    assert r.startswith("error:")                  # gone
    await coach.stop()


async def test_channel_dup_and_limit():
    coach, _ = await _coach()
    await _d(coach, {"type": "channel_open", "channel": "a",
                     "command": "nc -lnvp 9001"})
    r = await _d(coach, {"type": "channel_open", "channel": "a",
                         "command": "ssh x@10.1.10.21"})
    assert "already open" in r
    await _d(coach, {"type": "channel_open", "channel": "b",
                     "command": "ftp 10.1.10.21"})
    r = await _d(coach, {"type": "channel_open", "channel": "c",
                         "command": "telnet 10.1.10.21"})
    assert r.startswith("error:") and "limit" in r
    await coach.stop()


async def test_channel_open_scope_denied():
    scope = {"locked": True, "authorized_by": "op",
             "nets": ["203.0.113.0/29"], "hosts": [], "ports": []}
    coach, c = await _coach(scope)
    r = await _d(coach, {"type": "channel_open", "channel": "x",
                         "command": "ssh root@198.51.100.9"})
    assert r.startswith("denied:")
    assert "x" not in coach._channels
    assert not c.typed                            # nothing typed anywhere
    await coach.stop()


async def test_channel_send_pivot_denied():
    """An in-scope channel must not pivot out — `ssh` inside the channel
    to an out-of-scope IP is still a target connection."""
    scope = {"locked": True, "authorized_by": "op",
             "nets": ["203.0.113.0/29"], "hosts": [], "ports": []}
    coach, _c = await _coach(scope)
    await _d(coach, {"type": "channel_open", "channel": "x",
                     "command": "ssh user@203.0.113.3"})
    r = await _d(coach, {"type": "channel_send", "channel": "x",
                         "text": "ssh root@198.51.100.9"})
    assert r.startswith("denied:")
    await coach.stop()


async def test_channel_bad_names():
    coach, _ = await _coach()
    for bad in ("", "UPPER CASE", "x" * 20):
        r = await _d(coach, {"type": "channel_open", "channel": bad,
                             "command": "true"})
        assert r.startswith("error:")
    await coach.stop()


# ---------- ablation ----------

async def test_ablation_filters_tools_and_roles():
    coach, _ = await _coach()
    coach._ablate = {"coverage", "memory", "roles", "ptg"}
    coach.state.ablation = coach._ablate
    # spawn honors neither role nor task_id under ablation
    r = coach._spawn_agent({"task": "scan 10.1.10.21",
                            "role": "recon", "task_id": "p1"})
    assert "spawned" in r
    w = coach._workers["w1"]
    assert w.role == "general" and w.task_id == ""
    await coach.stop()
