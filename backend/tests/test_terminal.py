"""Browser terminal hub — wants registry, pairing, auth, lifecycle.

The pairing is in-memory (single uvicorn process), so these tests drive the
service directly with fake WebSockets: a user socket and a kali-agent socket
meet on a channel id and pump binary frames both ways.
"""
from __future__ import annotations

import asyncio
import json

import app.services.terminal as terminal_svc
from app.models.domain import Session, SessionState
from app.services.events import bus, publish_session


class _FakeWs:
    """Queue-backed fake WebSocket mimicking starlette's receive() shape."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent_bytes: list[bytes] = []
        self.sent_text: list[str] = []
        self.accepted = False
        self.closed_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict:
        return await self.inbox.get()

    async def send_bytes(self, b: bytes) -> None:
        self.sent_bytes.append(b)

    async def send_text(self, t: str) -> None:
        self.sent_text.append(t)

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code

    # test helpers
    def feed_bytes(self, b: bytes) -> None:
        self.inbox.put_nowait({"type": "websocket.receive", "bytes": b})

    def feed_text(self, t: str) -> None:
        self.inbox.put_nowait({"type": "websocket.receive", "text": t})

    def disconnect(self) -> None:
        self.inbox.put_nowait({"type": "websocket.disconnect"})

    def statuses(self) -> list[dict]:
        return [json.loads(t) for t in self.sent_text
                if json.loads(t).get("t") == "status"]


async def _session(db, state: str = SessionState.ACTIVE.value,
                   token: str = "tok") -> Session:
    s = Session(quest_id="q1", state=state, kali_vmid=103,
                flag_seed="x", telemetry_token=token)
    db.add(s)
    await db.commit()
    return s


async def _wait(cond, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met")


async def test_want_registration_and_poll(db):
    s = await _session(db)
    user = _FakeWs()
    task = asyncio.ensure_future(
        terminal_svc.user_terminal(db, user, s.id, "chan1", 100, 30))
    await _wait(lambda: user.accepted)

    assert (await terminal_svc.wants_for_agent(db, s.id, "tok")) == \
        {"chans": {"chan1": {"cols": 100, "rows": 30}}}
    # wrong / missing token sees nothing
    assert await terminal_svc.wants_for_agent(db, s.id, "bad") is None
    assert await terminal_svc.wants_for_agent(db, s.id, None) is None
    # waiting status was reported to the UI
    assert user.statuses() == [{"t": "status", "state": "waiting", "msg": ""}]

    user.disconnect()
    await asyncio.wait_for(task, timeout=2)


async def test_pairing_pumps_bytes_and_controls(db):
    s = await _session(db)
    user, kali = _FakeWs(), _FakeWs()
    utask = asyncio.ensure_future(
        terminal_svc.user_terminal(db, user, s.id, "chan1", 120, 32))
    await _wait(lambda: user.accepted)
    ktask = asyncio.ensure_future(
        terminal_svc.kali_terminal(db, kali, s.id, "chan1", "tok"))
    await _wait(lambda: kali.accepted)

    user.feed_bytes(b"ls -la\n")
    kali.feed_bytes(b"total 0\r\n")
    kali.feed_text(json.dumps({"t": "exit", "code": 0}))
    user.feed_text(json.dumps({"t": "resize", "cols": 200, "rows": 50}))
    await _wait(lambda: kali.sent_bytes == [b"ls -la\n"])
    await _wait(lambda: user.sent_bytes == [b"total 0\r\n"])
    await _wait(lambda: any('{"t": "exit", "code": 0}' == t
                            for t in user.sent_text))
    await _wait(lambda: any(json.loads(t).get("t") == "resize"
                            for t in kali.sent_text))
    assert json.loads([t for t in kali.sent_text
                       if json.loads(t).get("t") == "resize"][0])["cols"] == 200

    user.disconnect()
    await asyncio.wait_for(utask, timeout=2)
    await _wait(lambda: kali.closed_code is not None)
    kali.disconnect()
    await asyncio.wait_for(ktask, timeout=2)


async def test_auth_and_state_gates(db):
    s = await _session(db)
    kali = _FakeWs()
    await terminal_svc.kali_terminal(db, kali, s.id, "chan1", "wrong")
    assert kali.closed_code == 4401

    # no want registered -> kali dial rejected
    kali2 = _FakeWs()
    await terminal_svc.kali_terminal(db, kali2, s.id, "chanx", "tok")
    assert kali2.closed_code == 4404

    # session not ready -> user rejected
    s2 = await _session(db, state=SessionState.QUEUED.value)
    user = _FakeWs()
    await terminal_svc.user_terminal(db, user, s2.id, "chan1", 80, 24)
    assert user.closed_code == 4403

    # bad chan id
    user2 = _FakeWs()
    await terminal_svc.user_terminal(db, user2, s.id, "BAD!!", 80, 24)
    assert user2.closed_code == 4400


async def test_tab_cap(db):
    s = await _session(db)
    users = []
    tasks = []
    for i in range(terminal_svc.MAX_TABS):
        u = _FakeWs()
        users.append(u)
        tasks.append(asyncio.ensure_future(
            terminal_svc.user_terminal(db, u, s.id, f"cap{i}", 80, 24)))
    await _wait(lambda: all(u.accepted for u in users))
    extra = _FakeWs()
    await terminal_svc.user_terminal(db, extra, s.id, "chanz", 80, 24)
    assert extra.closed_code == 4429
    # cleanup
    for u in users:
        u.disconnect()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_drop_session_closes_both_sides(db):
    s = await _session(db)
    user, kali = _FakeWs(), _FakeWs()
    utask = asyncio.ensure_future(
        terminal_svc.user_terminal(db, user, s.id, "chan2", 80, 24))
    await _wait(lambda: user.accepted)
    ktask = asyncio.ensure_future(
        terminal_svc.kali_terminal(db, kali, s.id, "chan2", "tok"))
    await _wait(lambda: kali.accepted)

    await terminal_svc.drop_session(s.id)
    await _wait(lambda: kali.closed_code is not None
                and user.closed_code is not None)
    user.disconnect()
    kali.disconnect()
    await asyncio.gather(utask, ktask, return_exceptions=True)
    assert s.id not in terminal_svc._CHANS


async def test_janitor_drops_on_end_state_event(db):
    s = await _session(db)
    user = _FakeWs()
    utask = asyncio.ensure_future(
        terminal_svc.user_terminal(db, user, s.id, "chan3", 80, 24))
    await _wait(lambda: user.accepted)

    terminal_svc._start_janitor()
    # ensure_future schedules the janitor — wait until its subscription lands
    await _wait(lambda: bool(bus._subs.get("session.*")))
    await publish_session(s.id, "state", {"state": SessionState.ABORTED.value})
    await _wait(lambda: user.closed_code is not None)
    user.disconnect()
    await asyncio.wait_for(utask, timeout=2)


async def test_kali_drop_keeps_want_for_redial(db):
    s = await _session(db)
    user, kali = _FakeWs(), _FakeWs()
    utask = asyncio.ensure_future(
        terminal_svc.user_terminal(db, user, s.id, "chan4", 80, 24))
    await _wait(lambda: user.accepted)
    ktask = asyncio.ensure_future(
        terminal_svc.kali_terminal(db, kali, s.id, "chan4", "tok"))
    await _wait(lambda: kali.accepted)

    # agent dies (backend restart / network blip) -> want survives for re-dial
    kali.disconnect()
    await asyncio.wait_for(ktask, timeout=2)
    await _wait(lambda: "chan4" in terminal_svc._wants(s.id))
    assert user.statuses()[-1]["state"] in ("waiting", "live")

    kali2 = _FakeWs()
    ktask2 = asyncio.ensure_future(
        terminal_svc.kali_terminal(db, kali2, s.id, "chan4", "tok"))
    await _wait(lambda: kali2.accepted)
    user.feed_bytes(b"reconnected\n")
    await _wait(lambda: kali2.sent_bytes == [b"reconnected\n"])

    user.disconnect()
    kali2.disconnect()
    await asyncio.gather(utask, ktask2, return_exceptions=True)


async def _cleanup_all():
    for sid in list(terminal_svc._CHANS):
        await terminal_svc.drop_session(sid)
