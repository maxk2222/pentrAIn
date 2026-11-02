"""Autonomy-gated action dispatch — fake backend client."""
from __future__ import annotations

import asyncio
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

    async def exec_in_kali(self, sid, command, window=None):
        self.execs.append(command)
        return {"out": "done\n"}

    async def mark_checkpoint(self, sid, cid):
        self.checkpoints.append(cid)
        return {}

    async def send_activity(self, sid, text="", *, active=True, agent="main"):
        pass

    async def log_action(self, sid, tool, args, result, status="ok"):
        self.logged = getattr(self, "logged", [])
        self.logged.append({"tool": tool, "args": args})
        return {}


def _coach(autonomy: int, action_budget: int = 50,
           action_grace: int = 10) -> tuple[SessionCoach, FakeClient]:
    c = FakeClient()
    coach = SessionCoach(1, c, {"coach": {"action_budget": action_budget,
                                          "action_grace": action_grace,
                                          "nudge_after_s": 60,
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


async def test_busy_pane_bounces_without_marking_exec():
    """pane busy → nothing was typed: no exec_count, no stale _coach_cmds
    entry, the report says 'could not run' (never 'Executed'), and the
    tool result tells the model to interrupt or wait."""
    coach, c = _coach(autonomy=4)

    async def busy(sid, cmd, window=None):
        return {"out": "", "busy": True, "exitcode": None, "visible": True,
                "err": "pane busy: 'top' is still running — send 'C-c'"}
    c.exec_in_kali = busy
    _spoke, res = await coach._dispatch({"type": "exec_in_kali", "command": "nmap x"})
    assert "pane busy" in res
    assert coach.state.exec_count == 0 and not coach._coach_cmds
    assert any("Could not run" in m["content"] and "nmap x" in m["content"]
               for m in c.chats)
    assert not any("Executed" in m["content"] for m in c.chats)


async def test_timed_out_exec_reports_partial_output():
    coach, c = _coach(autonomy=4)

    async def slow(sid, cmd, window=None):
        return {"out": "partial output", "timed_out": True,
                "exitcode": None, "visible": True,
                "err": "still running — pane is now busy"}
    c.exec_in_kali = slow
    spoke, res = await coach._dispatch({"type": "exec_in_kali", "command": "nmap x"})
    assert spoke and "partial output" in res
    assert coach.state.exec_count == 1  # it WAS typed and is still running
    report = [m for m in c.chats if m["kind"] == "action_report"]
    assert "partial output" in report[0]["content"]
    assert "still running" in report[0]["content"]


async def test_infra_errors_backoff_and_guide():
    """s49: qga died ~12min mid-run; the agent retyped identical payloads
    9x into the dead channel. API-level `error` results must (a) carry an
    INFRA note so the model knows the command never ran, and (b) bounce
    after 3 consecutive errors until a probe succeeds."""
    coach, c = _coach(autonomy=4)

    async def dead_qga(sid, cmd, window=None):
        c.execs.append(cmd)
        return {"error": "POST /nodes/pentrain/qemu/103/agent/exec -> 500: "
                         "QEMU guest agent is not running", "status": "error"}
    c.exec_in_kali = dead_qga
    for _ in range(3):
        _, res = await coach._dispatch(
            {"type": "exec_in_kali", "command": "cat /f"})
    assert "INFRA" in res and "never ran" in res
    # first call past the threshold is the recovery probe — it goes through
    ok, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "echo ok"})
    assert ok and "INFRA" in res
    # channel still down → further execs bounce instead of reaching the backend
    c.execs.clear()
    ok, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "cat /f"})
    assert not ok and "unreachable" in res and not c.execs
    # probe window opens after the cooldown — the probe is typed again
    coach._infra_last_probe = 0.0
    ok, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "echo ok"})
    assert ok and "INFRA" in res and c.execs == ["echo ok"]
    # channel back → the probe succeeds, counter resets, execs flow again
    async def healthy(sid, cmd, window=None):
        c.execs.append(cmd)
        return {"out": "ok\n", "exitcode": 0}
    c.exec_in_kali = healthy
    coach._infra_last_probe = 0.0   # probe window open
    ok, _ = await coach._dispatch({"type": "exec_in_kali", "command": "id"})
    assert ok and coach._infra_errors == 0
    ok, _ = await coach._dispatch({"type": "exec_in_kali", "command": "id2"})
    assert ok


async def test_takeover_budget_cap():
    coach, c = _coach(autonomy=4, action_budget=2, action_grace=0)
    await coach._dispatch({"type": "exec_in_kali", "command": "a"})
    await coach._dispatch({"type": "exec_in_kali", "command": "b"})
    ok, res = await coach._dispatch({"type": "exec_in_kali", "command": "c"})
    assert not ok and "budget" in res and c.execs == ["a", "b"]


async def test_denial_match_blocks_retry():
    """s46: `mysql -u root` + DEPLOY_PASS was 1045-denied, then retried
    verbatim after a restart. Settled denials must STOP the exec before
    typing — the facts render alone doesn't."""
    coach, c = _coach(autonomy=4)
    coach.facts.denials = [
        "denied:mysql-root@shop01",
        "denied:sudo@shop01",
        "unreachable:172.20.1.2@shop01",
    ]
    # same svc + user + pivot → blocked before typing
    _ok, res = await coach._dispatch({"type": "exec_in_kali", "command":
        "sshpass -p 'x' ssh deploy@shop01 'mysql -h 172.20.1.3 -u root -pY'"})
    assert res.startswith("denied: prior evidence")
    assert not c.execs
    # bare sudo on the same pivot → blocked
    _ok, res = await coach._dispatch({"type": "exec_in_kali", "command":
        "sshpass -p 'x' ssh deploy@shop01 'sudo docker ps'"})
    assert "denied" in res and not c.execs
    # unreachable target via the same vantage → blocked
    _ok, res = await coach._dispatch({"type": "exec_in_kali", "command":
        "sshpass -p 'x' ssh deploy@shop01 'curl http://172.20.1.2:8080/'"})
    assert "denied" in res and not c.execs
    # DIFFERENT user is a new path → allowed
    _ok, res = await coach._dispatch({"type": "exec_in_kali", "command":
        "sshpass -p 'x' ssh deploy@shop01 'mysql -h 172.20.1.3 -u shop_ro -pY'"})
    assert not res.startswith("denied") and c.execs
    # unreachable from a DIFFERENT vantage stays allowed (may route)
    _ok, res = await coach._dispatch({"type": "exec_in_kali", "command":
        "curl -s --max-time 10 http://172.20.1.2:8080/"})
    assert not res.startswith("denied: prior")
    # -auth denials must NOT brick the working pivot
    coach.facts.denials.append("denied:ssh-auth@shop01")
    _ok, res = await coach._dispatch({"type": "exec_in_kali", "command":
        "sshpass -p 'GOOD' ssh deploy@shop01 'id'"})
    assert not res.startswith("denied: prior")


async def test_budget_grace_window():
    """s46: a hard stop froze the agent mid-flag-chain. Over-budget execs
    run inside a labelled grace window, then the wall still stands."""
    coach, c = _coach(autonomy=4, action_budget=1, action_grace=2)
    await coach._dispatch({"type": "exec_in_kali", "command": "a"})
    # 1st grace exec — allowed, labelled, operator got the one-shot note
    ok, res = await coach._dispatch({"type": "exec_in_kali", "command": "b"})
    assert ok and c.execs[-1] == "b"
    assert res.startswith("GRACE 1/2")
    notes = [m for m in c.chats if m["kind"] == "nudge"
             and "grace window" in m["content"]]
    assert len(notes) == 1
    # 2nd grace exec — still allowed, note NOT repeated
    ok, res = await coach._dispatch({"type": "exec_in_kali", "command": "c2"})
    assert ok and res.startswith("GRACE 2/2")
    assert len([m for m in c.chats if m["kind"] == "nudge"
                and "grace window" in m["content"]]) == 1
    # grace exhausted — hard wall
    ok, res = await coach._dispatch({"type": "exec_in_kali", "command": "d"})
    assert not ok and "grace" in res and "action_budget" in res


async def test_telemetry_event_feeds_state():
    coach, _c = _coach(autonomy=4)
    ev = {"type": "telemetry", "topic": "telemetry.1",
          "data": {"session_id": 1, "kind": "command",
                   "payload": {"command": "nmap -sV 10.0.0.5", "ts": time.time()}}}
    coach.matcher = type("M", (), {"check": lambda self, cmd: []})()
    await coach._handle_event(ev)
    assert coach.state.recent_commands(1) == ["nmap -sV 10.0.0.5"]


async def test_wait_sleeps_and_reports():
    coach, c = _coach(4)
    t0 = time.monotonic()
    spoke, res = await coach._dispatch(
        {"type": "wait", "seconds": 2, "why": "root cron"})
    assert spoke and res.startswith("waited") and time.monotonic() - t0 >= 1.5
    card = c.chats[-1]
    assert card["kind"] == "action_report" and "Waiting 2s" in card["content"]
    assert "root cron" in card["content"]


async def test_wait_denied_below_l4():
    coach, c = _coach(2)
    spoke, res = await coach._dispatch({"type": "wait", "seconds": 5})
    assert not spoke and res.startswith("denied:") and not c.chats


async def test_wait_aborts_on_pending_chat():
    coach, _c = _coach(4)

    async def _flag_soon():
        await asyncio.sleep(0.3)
        coach.state.pending_chat.append("hi coach")

    task = asyncio.create_task(_flag_soon())
    t0 = time.monotonic()
    _spoke, res = await coach._dispatch({"type": "wait", "seconds": 30})
    await task
    assert time.monotonic() - t0 < 10
    assert "aborted" in res and "operator message" in res


async def test_wait_in_toolsets():
    from coach.loop import _CHAIN_TOOLS
    from coach.tools import WORKER_TOOL_NAMES, tools_for_level, worker_tools
    assert "wait" in WORKER_TOOL_NAMES and "wait" in _CHAIN_TOOLS
    assert "wait" in {t["function"]["name"] for t in worker_tools()}
    assert "wait" in {t["function"]["name"] for t in tools_for_level(4)}
    assert "wait" not in {t["function"]["name"] for t in tools_for_level(3)}


async def test_wait_caps_at_max():
    coach, _c = _coach(4)
    coach.cfg["coach"]["wait_max_s"] = 1
    t0 = time.monotonic()
    _spoke, res = await coach._dispatch({"type": "wait", "seconds": 999})
    assert time.monotonic() - t0 < 10 and res.startswith("waited 1s")


async def test_wait_streak_hint_and_reset():
    coach, _c = _coach(4)
    coach.cfg["coach"]["wait_max_s"] = 1
    for _ in range(2):
        await coach._dispatch({"type": "wait", "seconds": 1})
    _s, res = await coach._dispatch({"type": "wait", "seconds": 1})
    assert "consecutive waits" in res
    # any non-wait action clears the streak
    await coach._dispatch({"type": "exec_in_kali", "command": "id"})
    _s, res = await coach._dispatch({"type": "wait", "seconds": 1})
    assert "consecutive waits" not in res


async def test_wait_budget_guard():
    coach, c = _coach(4)
    coach._turn_deadline = time.monotonic() + 15   # <20s margin left
    spoke, res = await coach._dispatch({"type": "wait", "seconds": 60})
    assert not spoke and "too little turn budget" in res and not c.chats


async def test_worker_wait_uses_own_deadline():
    from coach.loop import _Worker
    coach, c = _coach(4)
    coach.cfg["coach"]["wait_max_s"] = 2
    # a nearly-exhausted PARENT turn deadline must not touch the worker's
    coach._turn_deadline = time.monotonic() + 15
    coach._workers["w1"] = _Worker(id="w1", task="enum",
                                   started=time.monotonic())
    spoke, res = await coach._dispatch(
        {"type": "wait", "seconds": 2, "why": "cron"}, window="w1")
    assert spoke and res.startswith("waited")
    card = c.chats[-1]
    assert card["meta"]["agent"] == "w1"
    assert coach._wait_streak["w1"] == 1
    assert coach._wait_streak.get("main", 0) == 0


async def test_update_plan_stores_normalizes_and_reports():
    coach, c = _coach(4)
    spoke, res = await coach._dispatch({"type": "update_plan", "items": [
        {"t": "loot creds from tarball", "s": "done"},
        {"t": "mysql LOAD_FILE via shop_ro", "s": "doing"},
        {"t": "read /root flags"}]})
    assert spoke
    assert coach.state.plan == [
        {"t": "loot creds from tarball", "s": "done"},
        {"t": "mysql LOAD_FILE via shop_ro", "s": "doing"},
        {"t": "read /root flags", "s": "todo"}]
    assert "2 open" in res and "[x]" in res and "[>]" in res
    # persistence + feed report
    await asyncio.sleep(0)
    assert any(l["tool"] == "update_plan" and l["args"]["agent"] == "main"
               for l in c.logged)
    card = next(k for k in c.chats if k["kind"] == "plan_update")
    assert "2 open / 3 steps" in card["content"]
    # structured items ride in meta — the feed renders a checklist card
    assert card["meta"]["plan"] == coach.state.plan
    assert card["meta"]["open"] == 2


async def test_update_plan_all_levels_and_atomic_replace():
    coach, _c = _coach(1)          # bookkeeping — allowed everywhere
    await coach._dispatch({"type": "update_plan",
                           "items": [{"t": "nudge next", "s": "doing"}]})
    assert len(coach.state.plan) == 1
    # full-replace: second call replaces, never appends zombie steps
    await coach._dispatch({"type": "update_plan",
                           "items": [{"t": "only step left", "s": "done"}]})
    assert coach.state.plan == [{"t": "only step left", "s": "done"}]


async def test_update_plan_worker_owns_its_plan():
    from coach.loop import _Worker
    coach, c = _coach(4)
    coach.state.plan = [{"t": "parent phase", "s": "doing"}]
    coach._workers["w1"] = _Worker(id="w1", task="enum",
                                   started=time.monotonic())
    spoke, _res = await coach._dispatch(
        {"type": "update_plan",
         "items": [{"t": "w step", "s": "doing"}]}, window="w1")
    assert spoke
    assert coach._workers["w1"].plan == [{"t": "w step", "s": "doing"}]
    assert coach.state.plan == [{"t": "parent phase", "s": "doing"}]
    await asyncio.sleep(0)
    assert any(l["args"]["agent"] == "w1" for l in c.logged
               if l["tool"] == "update_plan")
    # parent sees worker intent via agent_status
    _s, st = await coach._dispatch({"type": "agent_status"})
    assert "w step" in st
