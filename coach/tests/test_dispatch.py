"""Autonomy-gated action dispatch — fake backend client."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.loop import SessionCoach


class FakeClient:
    def __init__(self):
        self.chats: list[dict] = []
        self.suggestions: list[dict] = []
        self.execs: list[str] = []
        self.checkpoints: list[str] = []

    async def send_chat(self, sid, content, *, kind="chat", meta=None):
        self.chats.append({"content": content, "kind": kind, "meta": meta})
        return {}

    async def suggest_command(self, sid, command, why):
        self.suggestions.append({"command": command, "why": why})
        return {}

    async def exec_in_kali(self, sid, command):
        self.execs.append(command)
        return {"out": "done\n"}

    async def mark_checkpoint(self, sid, cid):
        self.checkpoints.append(cid)
        return {}

    async def send_activity(self, sid, text="", *, active=True):
        pass


def _coach(autonomy: int, action_budget: int = 50) -> tuple[SessionCoach, FakeClient]:
    c = FakeClient()
    coach = SessionCoach(1, c, {"coach": {"action_budget": action_budget, "nudge_after_s": 60,
                                          "hint_after_s": 120}})
    coach.state.autonomy_level = autonomy
    coach.state.state = "active"
    return coach, c


async def test_advisor_can_chat_but_not_execute():
    coach, c = _coach(autonomy=2)
    spoke, _ = await coach._dispatch({"type": "send_chat", "content": "hi"})
    assert spoke
    assert (await coach._dispatch({"type": "suggest_command", "command": "nmap 1.2.3.4"}))[0] is False
    assert (await coach._dispatch({"type": "exec_in_kali", "command": "id"}))[0] is False
    assert len(c.chats) == 1 and not c.execs and not c.suggestions


async def test_copilot_suggests_but_never_execs():
    coach, c = _coach(autonomy=3)
    assert (await coach._dispatch({"type": "suggest_command", "command": "nmap -sV 10.0.0.5"}))[0]
    denied, res = await coach._dispatch({"type": "exec_in_kali", "command": "id"})
    assert denied is False and "denied" in res
    assert len(c.suggestions) == 1 and not c.execs


async def test_takeover_executes_and_reports():
    coach, c = _coach(autonomy=4)
    spoke, res = await coach._dispatch({"type": "exec_in_kali", "command": "whoami"})
    assert spoke and res
    assert c.execs == ["whoami"]
    assert coach.state.exec_count == 1
    report = [m for m in c.chats if m["kind"] == "action_report"]
    assert report and "whoami" in report[0]["content"]


async def test_takeover_budget_cap():
    coach, c = _coach(autonomy=4, action_budget=2)
    await coach._dispatch({"type": "exec_in_kali", "command": "a"})
    await coach._dispatch({"type": "exec_in_kali", "command": "b"})
    ok, res = await coach._dispatch({"type": "exec_in_kali", "command": "c"})
    assert not ok and "budget" in res and c.execs == ["a", "b"]
    assert any("budget" in m["content"] for m in c.chats)


async def test_telemetry_event_feeds_state():
    coach, _c = _coach(autonomy=4)
    ev = {"type": "telemetry", "topic": "telemetry.1",
          "data": {"session_id": 1, "kind": "command",
                   "payload": {"command": "nmap -sV 10.0.0.5", "ts": time.time()}}}
    coach.matcher = type("M", (), {"check": lambda self, cmd: []})()
    await coach._handle_event(ev)
    assert coach.state.recent_commands(1) == ["nmap -sV 10.0.0.5"]
