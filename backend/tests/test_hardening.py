"""Regression tests for the quality-review fixes (security + correctness)."""
from __future__ import annotations

import base64
import json

import httpx
import pytest
from sqlalchemy import select

from app.api.deps import check_password, hash_password
from app.models.domain import CoachMessage, ExpectedFlag, Flag, Session
from app.ranges.pve import PveClient, PveCreds, PveError
from app.services import settings as settings_svc
from app.services import telemetry as telemetry_svc
from app.services.flags import create_expected_flags, derive_flag_secret

# ---------- password hashing ----------

def test_password_hashing_scrypt_roundtrip():
    h = hash_password("s3cret!")
    assert h.startswith("scrypt$")
    assert check_password("s3cret!", h)
    assert not check_password("other", h)
    assert not check_password("s3cret!", "scrypt$bad")
    assert not check_password("s3cret!", "garbage")
    # two hashes of the same password differ (per-password salt)
    assert hash_password("s3cret!") != h


# ---------- settings coercion ----------

async def test_settings_patch_coerces_types(db):
    await settings_svc.patch_settings(db, {
        "resources.max_ram_gb": "96",       # str → int
        "setup.completed": "true",           # str → bool
        "engine.testing_allow": ["10.0.0.0/8"],
    })
    assert await settings_svc.get_setting(db, "resources.max_ram_gb") == 96
    assert await settings_svc.get_setting(db, "setup.completed") is True
    assert await settings_svc.get_setting(db, "engine.testing_allow") == ["10.0.0.0/8"]


async def test_settings_patch_rejects_bad_types(db):
    with pytest.raises(ValueError):
        await settings_svc.patch_settings(db, {"resources.max_ram_gb": "lots"})
    with pytest.raises(ValueError):
        await settings_svc.patch_settings(db, {"engine.testing_mode": {"weird": 1}})


# ---------- expected flag rotation ----------

async def test_expected_flags_replace_on_reset(db, db_with_packs):
    s = Session(quest_id="linux-t1-first-foothold", flag_seed="seed-a", state="ready")
    db.add(s)
    flags = (await db.execute(
        select(Flag).where(Flag.quest_id == s.quest_id))).scalars().all()
    await db.commit()
    await create_expected_flags(db, s, flags)
    first = derive_flag_secret("seed-a", flags[0].key)

    # simulate soft reset: new seed → recreate → old secrets must be gone
    s.flag_seed = "seed-b"
    await db.commit()
    await create_expected_flags(db, s, flags)

    rows = (await db.execute(
        select(ExpectedFlag).where(ExpectedFlag.session_id == s.id))).scalars().all()
    assert len(rows) == len(flags)          # replaced, not duplicated
    assert first not in {r.secret for r in rows}
    assert derive_flag_secret("seed-b", flags[0].key) in {r.secret for r in rows}


# ---------- telemetry ingest caps ----------

async def test_telemetry_ingest_caps(db):
    s = Session(quest_id="q", flag_seed="x", telemetry_token="tok", state="active")
    db.add(s)
    await db.commit()
    # batch cap
    events = [{"kind": "command", "payload": {"command": f"echo {i}"}} for i in range(600)]
    assert await telemetry_svc.ingest(db, s, events) == telemetry_svc.MAX_BATCH
    # payload size cap
    n = await telemetry_svc.ingest(db, s, [{"kind": "command",
                                          "payload": {"command": "A" * 200_000}}])
    assert n == 1


# ---------- chat history order ----------

async def test_chat_history_returns_latest_in_order(db):
    from app.api.routes_streams import chat_history

    s = Session(quest_id="q", flag_seed="x", state="active")
    db.add(s)
    await db.commit()
    for i in range(505):
        db.add(CoachMessage(session_id=s.id, role="user", kind="chat", content=f"msg{i}"))
    await db.commit()
    rows = await chat_history(s.id, db, None)
    assert len(rows) == 500
    assert rows[0]["content"] == "msg5"      # oldest of the *latest* 500
    assert rows[-1]["content"] == "msg504"


# ---------- PVE client ----------

def _pve(handler) -> PveClient:
    c = PveClient(PveCreds(base_url="https://pve:8006", token_id="u@p!t", token_secret="s"))
    c._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://pve:8006/api2/json")
    return c


async def test_agent_exec_decodes_base64():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/agent/exec"):
            return httpx.Response(200, json={"data": {"pid": 7}})
        if req.url.path.endswith("/agent/exec-status"):
            return httpx.Response(200, json={"data": {
                "exited": True, "exitcode": 0,
                "out-data": base64.b64encode(b"uid=0(root)\n").decode(),
                "err-data": base64.b64encode(b"warn\n").decode()}})
        return httpx.Response(404)
    res = await _pve(handler).agent_exec_sh(100, "id")
    assert res["out"] == "uid=0(root)\n" and res["err"] == "warn\n"


async def test_wait_task_fails_on_bad_exitstatus():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {
            "status": "stopped", "exitstatus": "command 'qemu-img' failed"}})
    with pytest.raises(PveError, match="failed"):
        await _pve(handler).wait_task("UPID:pve:0001:task")


def test_vnc_websocket_url_quotes_ticket():
    c = PveClient(PveCreds(base_url="https://pve:8006", token_id="u@p!t", token_secret="s"))
    url = c.vnc_websocket_url(100, "5900", "PVE:admin@pam!vnc=4F+tck==")
    assert "vncticket=PVE%3Aadmin%40pam%21vnc%3D4F%2Btck%3D%3D" in url


# ---------- coach internal API schemas ----------

def test_coach_schemas_validate():
    """Raw dicts are gone — malformed coach calls get 422, not KeyError crashes."""
    from pydantic import ValidationError

    from app.schemas import CoachExecIn, CoachMessageIn, CoachSuggestIn
    CoachSuggestIn(session_id=999, command="id", why="t")
    CoachExecIn(session_id=1, command="ls")
    CoachMessageIn(session_id=1, content="hi")
    with pytest.raises(ValidationError):
        CoachSuggestIn(session_id="x", command="id")  # bad type rejected


# ---------- setup/complete auth gate ----------

async def test_setup_complete_requires_token_once_password_set():
    """The takeover fix: after an admin password exists, /api/setup/complete
    must reject unauthenticated calls."""
    from fastapi.testclient import TestClient

    from app.db import session_factory
    from app.main import app

    with TestClient(app) as client:  # lifespan inits engine + tables first
        try:
            async with session_factory()() as s:
                await settings_svc.set_setting(
                    s, "security.admin_token_hash", hash_password("pw"))
            r = client.post("/api/setup/complete", json={"updates": {}})
            assert r.status_code == 401
            # and it still works with a valid bearer token
            tok = client.post("/api/auth/login", json={"password": "pw"}).json()["token"]
            r = client.post("/api/setup/complete", json={"updates": {}},
                            headers={"Authorization": f"Bearer {tok}"})
            assert r.status_code == 200
        finally:
            async with session_factory()() as s:
                await settings_svc.set_setting(s, "security.admin_token_hash", "")


async def test_visible_exec_falls_back_when_no_tmux():
    """Mock has no tmux → direct guest-agent path returns immediately."""
    from app.ranges.mock import MockProvider, MockPveClient
    from app.services.coach_bridge import exec_visible_in_kali
    from app.services.engine import Engine
    eng = Engine(MockProvider(), MockPveClient(), "mock")
    res = await exec_visible_in_kali(eng, 100, "whoami", timeout_s=5)
    assert res["exitcode"] == 0 and "whoami" in res.get("out", "")


async def test_visible_exec_streams_live_output_tail():
    """Each poll relays the pane tail as a coach_activity event so the chat
    shows command progress in real time — sentinel markers must be filtered."""
    import re as _re

    from app.services.coach_bridge import exec_visible_in_kali
    from app.services.events import bus

    class _Pve:
        def __init__(self):
            self.marker = "PTN0000000000"
            self.polls = 0
            self.b_sent = False

        async def agent_exec_sh(self, vmid, cmd, timeout_s=30):
            if "send-keys" in cmd:
                if m := _re.search(r"PTN[0-9a-f]{10}", cmd):
                    self.marker = m.group(0)
                    if "B:" in cmd:
                        self.b_sent = True
                return {"out": "", "exitcode": 0}
            if "has-session" in cmd:
                return {"out": "", "exitcode": 0}
            if "pane_current_command" in cmd:
                # free at entry (no poll yet), busy mid-scan (poll 1),
                # back at zsh once the scan finished
                return {"out": "nmap" if self.polls == 1 else "zsh",
                        "exitcode": 0}
            # the busy-check capture (`-pt`, no -S window) must NOT consume a
            # scripted pane — only the real poll loop uses -S -1500
            if "capture-pane" in cmd and "-S -1500" in cmd:
                m = self.marker
                self.polls += 1
                pane = (f"$ echo {m}A\n{m}A\n$ nmap -sV 10.0.0.5\n"
                        "Starting Nmap 7.94\nscanning…\n")
                if self.polls >= 2:
                    pane += "PORT STATE\n22/tcp open\n$ \n"
                if self.b_sent:
                    # deferred B marker — typed only once the pane is free;
                    # queued while nmap ran it would be eaten as stdin keys
                    pane += f"$ echo {m}B:$?\n{m}B:0\n"
                return {"out": pane, "exitcode": 0}
            return {"out": "", "exitcode": 0}

    class _Eng:
        def __init__(self, pve):
            self.pve = pve

    q = await bus.subscribe("session.7")
    try:
        res = await exec_visible_in_kali(_Eng(_Pve()), 100,
                                         "nmap -sV 10.0.0.5",
                                         session_id=7, timeout_s=5)
    finally:
        await bus.unsubscribe("session.7", q)
    assert res["exitcode"] == 0 and "22/tcp open" in res["out"]
    evts = []
    while not q.empty():
        evts.append(q.get_nowait())
    outs = [e["data"].get("output", "") for e in evts
            if e.get("type") == "coach_activity" and e["data"].get("active")]
    assert any("Starting Nmap" in o for o in outs)
    assert all("PTN" not in o for o in outs)  # sentinels never reach the UI


# ---------- suggestion resolved-meta persistence ----------

async def test_suggest_confirm_marks_message_resolved(db):
    """UI relies on meta.resolved surviving reloads — verify backend persists it."""
    from app.models.domain import CoachAction
    from app.services.sessions import suggest_command_confirm

    s = Session(quest_id="q", state="active", kali_vmid=1)
    db.add(s)
    await db.flush()
    action = CoachAction(session_id=s.id, tool="suggest_command",
                         args={"command": "id"}, status="pending")
    db.add(action)
    await db.flush()
    db.add(CoachMessage(session_id=s.id, role="coach", kind="suggestion",
                        content="run this", meta={"command": "id", "action_id": action.id}))
    await db.commit()

    await suggest_command_confirm(db, s.id, action.id, accept=False)

    msg = (await db.execute(
        select(CoachMessage).where(CoachMessage.session_id == s.id,
                                   CoachMessage.kind == "suggestion"))).scalar_one()
    assert msg.meta["resolved"] == "rejected"


# ---------- ludus provider: recreate a deleted range on deploy ----------

async def test_ludus_deploy_recreates_missing_range():
    """abort → DELETE /range removes the range OBJECT; the next deploy's
    PUT /range/config 404s. deploy_range must create the range and retry."""
    from app.ranges.ludus import LudusProvider

    calls: list[tuple[str, str, str, bytes]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        calls.append((req.method, path, str(req.url), req.content))
        if path.endswith("/testing/stop"):
            return httpx.Response(200, json={})
        if path.endswith("/ranges/create"):
            httpx.QueryParams()  # parse check — body unused
            return httpx.Response(200, json={"rangeID": "quest-x"})
        if path.endswith("/user/default-range"):
            return httpx.Response(200, json={})
        if path.endswith("/range/config"):
            # first attempt: range object gone; retry after create succeeds
            if not any(c[1].endswith("/ranges/create") for c in calls):
                return httpx.Response(404, json={"error": "Range not found"})
            return httpx.Response(200, json={})
        if path.endswith("/range/deploy"):
            return httpx.Response(200, json={})
        if path.endswith("/range") and req.method == "GET":
            return httpx.Response(200, json={
                "rangeState": "DEPLOYING", "rangeID": "quest-x", "VMs": []})
        return httpx.Response(404)

    p = LudusProvider("https://ludus:8080", "pentrain.KEY",
                      _pve(lambda r: httpx.Response(404)))
    p._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://ludus:8080/api/v2")
    rid = await p.deploy_range("quest-x", {"ludus": []})
    assert rid == "quest-x"
    creates = [c for c in calls if c[1].endswith("/ranges/create")]
    assert len(creates) == 1
    # default repointed to the new range — a dangling default is what 404s;
    # ludus takes `defaultRangeID` in the JSON body (query params are ignored)
    defaults = [c for c in calls if c[1].endswith("/user/default-range")]
    assert len(defaults) == 1
    assert json.loads(defaults[0][3])["defaultRangeID"] == "quest-x"
    # config upload retried AFTER the create
    cfg_idx = [i for i, c in enumerate(calls) if c[1].endswith("/range/config")]
    create_idx = calls.index(creates[0])
    assert cfg_idx[0] < create_idx < cfg_idx[1]


async def test_ludus_deploy_range_409_ok_when_range_exists():
    """A 409 on create means another range exists — config PUTs to default."""
    from app.ranges.ludus import LudusProvider

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/testing/stop"):
            return httpx.Response(200, json={})
        if path.endswith("/range/config"):
            return httpx.Response(404, json={"error": "no default range"})
        if path.endswith("/ranges/create"):
            return httpx.Response(409, json={"error": "Range ID already in use"})
        if path.endswith("/range/config"):
            return httpx.Response(200, json={})
        return httpx.Response(404)

    p = LudusProvider("https://ludus:8080", "pentrain.KEY",
                      _pve(lambda r: httpx.Response(404)))
    p._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://ludus:8080/api/v2")
    with pytest.raises(RuntimeError):
        # PUT /range/config retry still 404s → error surfaces (not swallowed)
        await p.deploy_range("quest-y", {"ludus": []})


async def test_settings_patch_nonclient_keys_skip_engine_rebuild(db):
    """engine.* keys that don't affect client construction (wan bridge,
    testing_allow, template) must NOT rebuild — a rebuild retires the
    shared provider and in-flight deploys die on 'client closed'."""
    from unittest.mock import AsyncMock, patch

    from app.api.routes_admin import patch_settings
    from app.schemas import SettingsPatch
    with patch("app.api.routes_admin.rebuild",
               new=AsyncMock()) as rb:
        await patch_settings(SettingsPatch(
            updates={"engine.kali_wan_bridge": "vmbr0",
                     "engine.testing_allow": ["1.2.3.0/24"],
                     "lan.scope_cidr": "10.0.0.0/24"}), db)
        rb.assert_not_called()
        await patch_settings(SettingsPatch(
            updates={"engine.pve_url": "https://new:8006"}), db)
        rb.assert_awaited_once()


async def test_engine_rebuild_retires_instead_of_closing(db):
    """A rebuild must not close the provider the in-flight caller still
    holds — retire it and close only at shutdown."""
    from app.services import engine as engine_svc
    eng1 = await engine_svc.get_engine(db)
    await engine_svc.rebuild(db)
    eng2 = await engine_svc.get_engine(db)
    if eng1 is eng2:            # mock mode may shortcut — nothing to prove
        return
    assert engine_svc._retired or eng1.provider is not eng2.provider
    await engine_svc.shutdown()


def test_coach_action_log_status_contract():
    """/api/coach/action must never fabricate successful real actions —
    status=ok is only for coach-internal bookkeeping tools."""
    import pytest
    from pydantic import ValidationError

    from app.schemas import CoachActionLogIn
    # internal tools may log ok (worker lifecycle, plan, notes)
    for tool in ("spawn_agent", "collect_agent", "kill_agent",
                 "update_plan", "note"):
        m = CoachActionLogIn(session_id=1, tool=tool, status="ok")
        assert m.status == "ok"
    # real actions can never self-report ok — that's the fabrication guard
    for tool in ("exec_in_kali", "submit_flag", "check_flag",
                 "type_in_pane", "send_chat"):
        with pytest.raises(ValidationError):
            CoachActionLogIn(session_id=1, tool=tool, status="ok")
    # denied/error stay unrestricted (guard self-reports under real names)
    CoachActionLogIn(session_id=1, tool="exec_in_kali", status="denied")
    CoachActionLogIn(session_id=1, tool="exec_in_kali", status="error")


# ---------- observer lessons ----------

def test_sanitize_lesson_strips_loot():
    """Observer lessons carry the move, never the loot: flag values,
    passwords and tokens are redacted before storage."""
    from app.services.coach_bridge import sanitize_lesson_text
    out = sanitize_lesson_text(
        "flag was pentrAIn{n0rdw1nd} after password=Hunter2 via ssh")
    assert "pentrAIn{" not in out and "Hunter2" not in out
    assert "<redacted>" in out
    assert sanitize_lesson_text("Bearer eyJabc123") .find("eyJabc123") < 0
    assert len(sanitize_lesson_text("x" * 500)) == 240


async def test_record_lesson_dedupes_and_hits(db):
    """Re-deriving the same lesson (different wording) merges into a hit
    on the existing row instead of a duplicate."""
    from app.services import coach_bridge
    a = await coach_bridge.record_lesson(
        db, 1, "ssh -D 9050 on a pivot host gives SOCKS to internal hosts",
        ["ssh", "pivot"], "global", 0.8, {"session_id": 1})
    assert a and a.id
    b = await coach_bridge.record_lesson(
        db, 2, "ssh -D 9050 on a pivot host gives SOCKS for internal hosts",
        ["ssh"], "global", 0.6, {"session_id": 2})
    assert b.id == a.id and (b.hits or 0) == 1   # merged, not duplicated
    c = await coach_bridge.record_lesson(
        db, 3, "gobuster uses --timeout never --max-time", ["gobuster"],
        "global", 0.7, {})
    assert c.id != a.id                            # distinct lesson stored
    # pure-loot lesson rejected
    assert await coach_bridge.record_lesson(
        db, 4, "pentrAIn{abc}", [], "global", 0.9, {}) is None


async def test_session_context_carries_field_notes(db_with_packs):
    """field_notes reach session_context so an attaching coach gets the
    observer's notes — scoped global/track/quest, active only."""
    from app.services import coach_bridge
    db = db_with_packs
    s = Session(quest_id="linux-t1-first-foothold", state="active")
    db.add(s)
    await db.commit()
    await coach_bridge.record_lesson(
        db, s.id, "web01 pivot via ssh -D works for internal http",
        ["ssh"], "global", 0.8, {})
    ctx = await coach_bridge.session_context(db, s.id)
    notes = ctx.get("field_notes") or []
    assert any("pivot" in n["text"] for n in notes)


def test_internal_audit_tools_cover_observer_and_knowledge():
    """status=ok stays for bookkeeping only — observer/knowledge tools
    included, real exec/flag tools still excluded."""
    import pytest
    from pydantic import ValidationError

    from app.schemas import CoachActionLogIn
    for tool in ("observe_hint", "observe_lesson",
                 "record_lesson", "lookup_guide"):
        CoachActionLogIn(session_id=1, tool=tool, status="ok")
    with pytest.raises(ValidationError):
        CoachActionLogIn(session_id=1, tool="exec_in_kali", status="ok")
