"""Free-lab mode (topology.free) — scope guards off, flag/checkpoint
tools not offered, everything else unchanged."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach import tools as toolmod
from coach.loop import SessionCoach


class FakeClient:
    def __init__(self, free=False):
        self.ctx = {
            "session": {"id": 1, "state": "active", "autonomy_level": 4,
                        "coach_enabled": True, "subagents_enabled": True,
                        "free_mode": free},
            "session_tools": "nmap curl",
            "quest": {"title": "Free Lab", "track": "lab", "tier": 1,
                      "briefing": "b", "coach_context": "", "checkpoints": [],
                      "escalation": {},
                      "targets": []},
            "flags": [], "checkpoints_hit": [], "telemetry_tail": [],
            "messages": [], "exec_count": 0,
            "profile": {"track_levels": {"lab": 1}},
        }

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


class FakeLlm:
    model = "fake"

    async def chat(self, *a, **k):
        return {"content": "", "actions": [{"type": "none"}],
                "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}


async def _coach(free=True):
    c = FakeClient(free=free)
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start()
    return coach


async def test_free_mode_disables_foreign_guards():
    coach = await _coach(free=True)
    # foreign private IPs that would deny in a scoped quest pass freely
    assert coach._foreign_ip("nmap 10.99.99.1") is None
    assert coach._foreign_ip("ssh root@172.16.0.44") is None
    assert coach._foreign_host("curl https://evil.example.com") is None
    await coach.stop()


async def test_normal_session_still_denies_foreign_ip():
    coach = await _coach(free=False)
    coach.state.autonomy_level = 4
    coach.ctx["quest"]["targets"] = [{"name": "app01", "ip": "10.1.10.21"}]
    await coach.stop()
    coach2 = await _coach(free=False)
    # seed the baseline like start() does for targets
    import ipaddress
    coach2._allowed_nets.append(ipaddress.ip_network("10.1.10.0/24"))
    assert coach2._foreign_ip("nmap 10.99.99.1") == "10.99.99.1"
    await coach2.stop()


def test_free_toolset_drops_flag_tools():
    names = {t["function"]["name"]
             for t in toolmod.tools_for_level(4, subagents=True, free=True)}
    assert "submit_flag" not in names
    assert "check_flag" not in names
    assert "mark_checkpoint" not in names
    # the rest of the L4 surface stays
    for t in ("exec_in_kali", "type_in_pane", "run_playbook",
              "search_memory", "channel_open", "update_plan"):
        assert t in names
    # and without free everything is present
    names2 = {t["function"]["name"]
              for t in toolmod.tools_for_level(4, subagents=True)}
    assert "submit_flag" in names2 and "mark_checkpoint" in names2
