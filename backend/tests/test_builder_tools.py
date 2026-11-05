"""Builder tool layer — catalog reads, path safety, gates."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.domain import Quest, Session, SessionState
from app.services.builder_tools import ToolCtx, dispatch, tools_for_phase


@pytest.fixture
def ctx(db):
    return ToolCtx(db=db)


async def test_quest_catalog(ctx, db):
    db.add(Quest(id="q1", track_slug="web-appsec", tier=1, title="One",
                 pack_path="/x",
                 topology={"vms": [{"name": "v", "roles": ["r1"]}]}))
    db.add(Quest(id="gen1", track_slug="custom", tier=1, title="G",
                 pack_path="/y", generated=True))
    await db.commit()
    out = await dispatch(ctx, "quest_catalog", {})
    assert "q1 [web-appsec/t1] One" in out
    assert "(generated)" in out
    assert "roles: r1" in out


async def test_read_quest(ctx, db, tmp_path):
    pack = tmp_path / "q1"
    pack.mkdir()
    (pack / "quest.yaml").write_text("meta: {id: q1}")
    db.add(Quest(id="q1", track_slug="t", tier=1, title="One",
                 pack_path=str(pack)))
    await db.commit()
    out = await dispatch(ctx, "read_quest",
                         {"quest_id": "q1", "file": "quest.yaml"})
    assert "meta:" in out
    assert "error" in await dispatch(
        ctx, "read_quest", {"quest_id": "nope", "file": "quest.yaml"})
    out = await dispatch(ctx, "read_quest",
                         {"quest_id": "q1", "file": "../../etc/passwd"})
    assert "error" in out


async def test_read_role_path_safety(ctx):
    out = await dispatch(ctx, "read_role",
                         {"role": "../../../etc", "file": "passwd"})
    assert "error" in out
    out = await dispatch(ctx, "read_role",
                         {"role": "no-such-role", "file": "tasks/main.yml"})
    assert "error" in out


async def test_list_roles_and_templates(ctx):
    roles = await dispatch(ctx, "list_roles", {})
    assert "pentrain_" in roles
    tpls = await dispatch(ctx, "list_templates", {})
    assert "files" in tpls or ":" in tpls  # role: file list rows


async def test_web_gate(ctx):
    ctx.web_enabled = False
    for tool in ("web_search", "web_fetch", "query_vuln_db", "rss_feed",
                 "search_technique"):
        out = await dispatch(ctx, tool, {"query": "x", "feed": "list",
                                         "url": "http://x"})
        assert out.startswith("denied"), (tool, out)


async def test_kali_exec_gates(ctx, db):
    out = await dispatch(ctx, "kali_exec", {"command": "id"})
    assert out.startswith("denied")
    ctx.verify_session_id = 1
    out = await dispatch(ctx, "kali_exec", {"command": "rm -rf /"})
    assert out.startswith("denied")
    out = await dispatch(ctx, "kali_exec", {"command": "id"})
    assert "error" in out  # session 1 doesn't exist
    # live mock session → engine has no pve → honest error, no crash
    db.add(Session(id=1, quest_id="q", state=SessionState.ACTIVE.value,
                   kali_vmid=100))
    await db.commit()
    out = await dispatch(ctx, "kali_exec", {"command": "id"})
    assert "error" in out or "exit" in out


async def test_search_technique_offline(ctx):
    out = await dispatch(ctx, "search_technique", {"query": "suid"})
    # vendored refs must answer without any network
    assert "match" in out or "error" not in out


def test_tools_for_phase_unknown_tools():
    spec = tools_for_phase("chat", has_verify=False)
    names = {t["function"]["name"] for t in spec}
    assert names == {"quest_catalog", "read_quest", "list_roles",
                     "read_role", "list_templates", "web_search", "web_fetch",
                     "query_vuln_db", "rss_feed", "search_technique"}
