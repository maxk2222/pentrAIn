"""Exec-channel agent link — handshake, request correlation, fallback.

Fake WebSockets drive agent_ws directly (single-process registry). The rust
agent's contract: {"t":"hello","v":1} then request/reply correlated by `id`;
exec_done carries stdout/stderr/exitcode. Absent agent → request() returns
None so coach_bridge falls back to QGA.
"""
from __future__ import annotations

import asyncio
import json

import app.services.agent_link as link
import app.services.flags as flags_svc
from app.models.domain import Flag, FlagKind, Session, SessionState


class _FakeWs:
    def __init__(self) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.accepted = False
        self.closed_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict:
        return await self.inbox.get()

    async def receive_json(self) -> dict:
        m = await self.inbox.get()
        return json.loads(m["text"])

    async def send_json(self, m: dict) -> None:
        self.sent.append(m)

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code

    def feed_json(self, m: dict) -> None:
        self.inbox.put_nowait({"type": "websocket.receive",
                               "text": json.dumps(m)})

    def disconnect(self) -> None:
        self.inbox.put_nowait({"type": "websocket.disconnect"})


async def _session(db, token: str = "tok") -> Session:
    s = Session(quest_id="q1", state=SessionState.ACTIVE.value,
                kali_vmid=103, flag_seed="x", telemetry_token=token)
    db.add(s)
    await db.commit()
    return s


def _dial(db, sid: int, token: str | None = "tok") -> tuple[_FakeWs, asyncio.Task]:
    ws = _FakeWs()
    task = asyncio.ensure_future(link.agent_ws(db, ws, sid, token))
    return ws, task


async def _wait(cond, timeout_s: float = 2.0) -> None:
    for _ in range(int(timeout_s / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met")


async def _connect(db, sid: int) -> _FakeWs:
    ws, task = _dial(db, sid)
    ws.feed_json({"t": "hello", "v": 1})
    await _wait(lambda: link.is_online(sid))
    return ws


async def test_auth_rejects_bad_token(db):
    s = await _session(db)
    ws, _t = _dial(db, s.id, "bad")
    await _wait(lambda: ws.closed_code == 4401)
    assert not link.is_online(s.id)


async def test_offline_request_returns_none(db):
    s = await _session(db)
    assert not link.is_online(s.id)
    assert await link.request(s.id, {"t": "peek"}) is None


async def test_hello_registers_and_exec_roundtrip(db):
    s = await _session(db)
    ws = await _connect(db, s.id)
    req = asyncio.ensure_future(
        link.request(s.id, {"t": "raw", "cmd": "id"}))
    await _wait(lambda: bool(ws.sent))
    sent = ws.sent[-1]
    assert sent["t"] == "raw" and sent["cmd"] == "id" and "id" in sent
    ws.feed_json({"t": "exec_done", "id": sent["id"], "out": "uid=0",
                  "err": "", "exitcode": 0})
    res = await req
    assert res["exitcode"] == 0 and res["out"] == "uid=0"


async def test_request_timeout_errors_not_hang(db):
    s = await _session(db)
    await _connect(db, s.id)
    res = await link.request(s.id, {"t": "exec", "cmd": "x"},
                             timeout_s=0.05)
    assert res["status"] == "error" and "timeout" in res["error"]


async def test_disconnect_fails_pending_and_offlines(db):
    s = await _session(db)
    ws = await _connect(db, s.id)
    req = asyncio.ensure_future(link.request(s.id, {"t": "exec", "cmd": "x"}))
    await _wait(lambda: bool(ws.sent))
    ws.disconnect()
    res = await req
    assert res["status"] == "error"
    await _wait(lambda: not link.is_online(s.id))


async def test_reconnect_replaces_stale_socket(db):
    s = await _session(db)
    ws1 = await _connect(db, s.id)
    ws2, _t = _dial(db, s.id)
    ws2.feed_json({"t": "hello", "v": 1})
    await _wait(lambda: ws1.closed_code == 4000)
    # the new socket now answers
    req = asyncio.ensure_future(link.request(s.id, {"t": "peek"}))
    await _wait(lambda: bool(ws2.sent))
    ws2.feed_json({"t": "exec_done", "id": ws2.sent[-1]["id"], "out": "p",
                   "exitcode": 0})
    assert (await req)["out"] == "p"


async def test_drop_session_closes_socket(db):
    s = await _session(db)
    ws = await _connect(db, s.id)
    await link.drop_session(s.id)
    assert ws.closed_code is not None
    assert not link.is_online(s.id)


async def test_flag_check_uses_agent_raw(db, monkeypatch):
    """kali-targeted command flags route through the agent when online —
    no QGA call at all."""
    s = await _session(db)
    db.add(Flag(quest_id="q1", key="f1", kind=FlagKind.COMMAND.value,
                name="f", points=1,
                command_spec={"vm": "kali", "cmd": "grep ok /f",
                              "expect": "yes"}))
    await db.commit()
    ws = await _connect(db, s.id)

    class _NoPve:
        async def agent_exec_sh(self, *a, **kw):  # QGA must not be touched
            raise AssertionError("QGA called while agent online")
    engine = type("E", (), {"pve": _NoPve()})()

    flag = (await db.execute(flags_svc.select(Flag))).scalars().first()
    task = asyncio.ensure_future(
        flags_svc.check_command_flag(db, engine, s, flag))
    await _wait(lambda: bool(ws.sent))
    assert ws.sent[-1]["t"] == "raw" and "grep ok /f" in ws.sent[-1]["cmd"]
    ws.feed_json({"t": "exec_done", "id": ws.sent[-1]["id"],
                  "out": "yes ok", "exitcode": 0})
    assert await task is True


async def test_flag_check_falls_back_to_qga(db):
    """Agent offline → the same check runs through the QGA path."""
    s = await _session(db)
    db.add(Flag(quest_id="q1", key="f1", kind=FlagKind.COMMAND.value,
                name="f", points=1,
                command_spec={"vm": "kali", "cmd": "grep ok /f",
                              "expect": "yes"}))
    await db.commit()

    class _Pve:
        async def agent_exec_sh(self, vmid, cmd):
            return {"out": "yes ok", "exitcode": 0}
    engine = type("E", (), {"pve": _Pve()})()
    flag = (await db.execute(flags_svc.select(Flag))).scalars().first()
    assert await flags_svc.check_command_flag(db, engine, s, flag) is True
