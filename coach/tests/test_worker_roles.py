"""Worker roles + orchestrator bias: role-gated tool subsets, spawn role/
done_when plumbing, role fragments in the worker prompt, and the parent's
ledger-driven delegate hint."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.loop import SessionCoach, _Worker
from coach.prompts import render_worker_prompt
from coach.tools import WORKER_ROLES, WORKER_TOOL_NAMES, worker_tools


def test_verify_role_drops_bookkeeping_tools():
    names = {t["function"]["name"] for t in worker_tools("verify")}
    assert "update_plan" not in names
    assert "record_lesson" not in names
    assert {"exec_in_kali", "type_in_pane", "wait", "none"} <= names
    # general + unknown roles keep the full worker set
    full = {t["function"]["name"] for t in worker_tools("general")}
    assert full == WORKER_TOOL_NAMES
    assert {t["function"]["name"] for t in worker_tools("bogus")} == full


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
        self.chats = []
        self.exec_calls = []
        self.logged = []

    async def send_chat(self, sid, content, *, kind="chat", meta=None):
        self.chats.append({"content": content, "kind": kind, "meta": meta})
        return {}

    async def session_context(self, sid):
        return self.ctx

    async def log_action(self, sid, tool, args, result, status="ok"):
        self.logged.append({"tool": tool, "args": args})
        return {}

    async def stream_draft(self, *a, **k):
        pass

    async def send_activity(self, *a, **k):
        pass

    async def send_agents(self, sid, agents):
        pass

    async def exec_in_kali(self, sid, command, window=None):
        self.exec_calls.append((command, window))
        return {"out": "ok", "exitcode": 0, "visible": True}

    async def report_llm_usage(self, *a, **k):
        return {}


def _coach():
    c = _FakeClient()
    return SessionCoach(1, c, {"coach": {"max_workers": 4}, "llm": {}}), c


async def test_spawn_agent_carries_role_and_done_when():
    coach, c = _coach()
    await coach.start()
    # worker never finishes so we can inspect the roster entry
    coach.llm = type("L", (), {"chat": staticmethod(
        lambda *a, **k: asyncio.sleep(60)), "model": "fake"})()
    _v, r = await coach._dispatch(
        {"type": "spawn_agent", "task": "scan hosts",
         "role": "recon", "done_when": "all live hosts have port lists"})
    assert "spawned w1" in r
    w = coach._workers["w1"]
    assert w.role == "recon"
    assert w.done_when == "all live hosts have port lists"
    await asyncio.sleep(0)          # log_action rides create_task
    # spawn log carries the role for the audit trail
    spawn_row = next(x for x in c.logged if x["tool"] == "spawn_agent")
    assert spawn_row["args"]["role"] == "recon"
    await coach._dispatch({"type": "kill_agent", "worker_id": "w1"})
    await coach.stop()


async def test_spawn_agent_unknown_role_falls_back():
    coach, _c = _coach()
    await coach.start()
    coach.llm = type("L", (), {"chat": staticmethod(
        lambda *a, **k: asyncio.sleep(60)), "model": "fake"})()
    _v, r = await coach._dispatch(
        {"type": "spawn_agent", "task": "x", "role": "ninja"})
    assert "spawned w1" in r
    assert coach._workers["w1"].role == "general"
    await coach._dispatch({"type": "kill_agent", "worker_id": "w1"})
    await coach.stop()


def test_worker_prompt_renders_role_and_done_when():
    w = _Worker(id="w3", task="t", role="verify",
                done_when="every vuln re-run")
    out = render_worker_prompt(
        {"quest": {"title": "Q", "track": "net", "targets": []}},
        w, turn_cap=10, time_cap_s=300)
    assert "ROLE: verify" in out
    assert "DONE WHEN: every vuln re-run" in out
    assert "coverage" in out           # extended report contract
    assert "vulns" in out


def test_worker_prompt_without_role_stays_generic():
    w = _Worker(id="w1", task="t")
    out = render_worker_prompt(
        {"quest": {"title": "Q", "track": "net", "targets": []}},
        w, turn_cap=10, time_cap_s=300)
    assert "ROLE:" not in out
    assert "DONE WHEN:" not in out


def test_audit_worker_roles_are_registered_and_scoped():
    for role in ("ai-audit", "cloud-audit", "exploit-audit", "linux-audit"):
        assert role in WORKER_ROLES
        worker = _Worker(id="w1", task="review local evidence", role=role)
        prompt = render_worker_prompt(
            {"quest": {"title": "Audit", "track": "audit", "targets": []}},
            worker, turn_cap=10, time_cap_s=300)
        assert f"ROLE: {role}" in prompt
        assert "local synthetic" in prompt or "local permission" in prompt
        assert "Do not" in prompt


async def test_ledger_delegate_hint_fires_once():
    """Parent scans an ip already tracked as untested while a worker slot
    is free → one advisory nudging spawn_agent, never a deny."""
    coach, _c = _coach()
    await coach.start()
    coach.state.subagents_enabled = True
    coach.state.coverage.record("192.168.3.55:80", "web", "untested")
    _v, r = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "nmap -sV -p80 192.168.3.55"}, proactive=True)
    assert "worker slot is free" in r and "spawn_agent" in r
    _v, r2 = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "nmap -sV -p443 192.168.3.55"}, proactive=True)
    assert "worker slot is free" not in r2   # once per ip, not a nag
    await coach.stop()


async def test_no_hint_when_surface_settled():
    coach, _c = _coach()
    await coach.start()
    coach.state.subagents_enabled = True
    coach.state.coverage.record("192.168.3.55:80", "web", "confirmed")
    _v, r = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "nmap -sV -p80 192.168.3.55"}, proactive=True)
    assert "worker slot is free" not in r
    await coach.stop()
