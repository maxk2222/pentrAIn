"""Native tool calling: schema coverage, call normalization, history
pairing/folding/trimming, and the loop's assistant+tool history replay."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_loop_reactions import FakeClient, FakeLlm

from coach.llm import ALLOWED_ACTIONS, LlmClient, _fold_history
from coach.loop import SessionCoach
from coach.tools import TOOL_NAMES, TOOLS, call_to_action, calls_to_actions, trim_history, wire_history

# ---------- schema contract ----------

def test_tool_names_cover_all_allowed_actions():
    # drift between schema set and parser set is exactly what native tools
    # are supposed to eliminate — pin it so one source can never diverge
    assert TOOL_NAMES == ALLOWED_ACTIONS


def test_every_tool_is_a_valid_function_schema():
    for t in TOOLS:
        fn = t["function"]
        assert t["type"] == "function" and fn["name"] and fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        for req in params["required"]:
            assert req in params["properties"], f"{fn['name']}.{req}"


# ---------- call → action normalization ----------

def _call(name, args=None, cid="c1", raw=None):
    return {"id": cid, "type": "function",
            "function": {"name": name,
                         "arguments": raw if raw is not None
                         else __import__("json").dumps(args or {})}}


def test_call_to_action_maps_args_and_keeps_call_id():
    a = call_to_action(_call("exec_in_kali", {"command": "id"}, cid="c9"))
    assert a == {"type": "exec_in_kali", "command": "id", "_call_id": "c9"}


def test_call_to_action_drops_unknown_and_malformed():
    assert call_to_action(_call("rm_rf_everything")) is None
    assert call_to_action(_call("send_chat", raw="{not json")) is None
    assert call_to_action(_call("send_chat", raw='["a"]')) is None
    # missing id still yields an action — pairing falls back to call_i
    a = call_to_action(_call("none", {"reason": "quiet"}, cid=None))
    assert a == {"type": "none", "reason": "quiet"}


def test_calls_to_actions_content_plus_calls_sends_chat_first():
    msg = {"content": "try this first",
           "tool_calls": [_call("exec_in_kali", {"command": "nmap x"})]}
    acts = calls_to_actions(msg)
    assert [a["type"] for a in acts] == ["send_chat", "exec_in_kali"]
    assert acts[0]["content"] == "try this first"


def test_calls_to_actions_none_and_blank_content_safe():
    assert calls_to_actions({"content": None}) == [{"type": "none"}]
    assert calls_to_actions({"content": "  \n "}) == [{"type": "none"}]
    # whitespace content + calls → calls only, no phantom send_chat
    acts = calls_to_actions({"content": "\n",
                             "tool_calls": [_call("mark_checkpoint",
                                                  {"checkpoint_id": "c1"})]})
    assert [a["type"] for a in acts] == ["mark_checkpoint"]


def test_calls_to_actions_plain_text_becomes_chat():
    assert calls_to_actions({"content": "hi there"}) == [
        {"type": "send_chat", "content": "hi there"}]


# ---------- wire history & trimming ----------

def test_wire_history_passthrough_when_tools_active():
    msgs = [{"role": "user", "content": "q"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c"}]},
            {"role": "tool", "tool_call_id": "c", "content": "ok"}]
    assert wire_history(msgs, tools_active=True) == msgs


def test_wire_history_strips_tool_artifacts_when_inactive():
    msgs = [{"role": "user", "content": "q"},
            {"role": "assistant", "content": "a",
             "tool_calls": [{"id": "c"}]},
            {"role": "tool", "tool_call_id": "c", "content": "res"},
            {"role": "user", "content": "next"}]
    out = wire_history(msgs, tools_active=False)
    assert all(m.get("role") != "tool" for m in out)
    assert all("tool_calls" not in m for m in out)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]


def test_trim_history_never_leaves_orphan_tool_reply():
    msgs = [{"role": "assistant", "content": None, "tool_calls": [{"id": "c"}]},
            {"role": "tool", "tool_call_id": "c", "content": "r1"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"}]
    out = trim_history(msgs, cap=3)
    # asst(tool_calls) dropped with the cap → its tool reply must not lead
    assert out[0]["role"] != "tool"
    assert [m["role"] for m in out] == ["user", "assistant"]


def test_wire_history_drops_leading_assistant_for_template_compat():
    """LM-Studio-style jinja templates 400 when the first non-system message
    isn't a user turn ('No user query found') — a seeded assistant welcome
    must never reach the wire."""
    msgs = [{"role": "assistant", "content": "welcome"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "answer"}]
    for active in (True, False):
        out = wire_history(msgs, tools_active=active)
        assert out[0]["role"] == "user", active


def test_wire_history_all_assistant_collapses_to_empty():
    out = wire_history([{"role": "assistant", "content": "w"},
                        {"role": "tool", "tool_call_id": "c", "content": "r"}],
                       tools_active=True)
    assert out == []


def test_fold_history_serializes_tool_exchange_as_text():
    msgs = [{"role": "system", "content": "sys"},
            {"role": "assistant", "content": None,
             "tool_calls": [_call("exec_in_kali", {"command": "id"})]},
            {"role": "tool", "tool_call_id": "c1", "content": "uid=0"},
            {"role": "user", "content": "next"}]
    out = _fold_history(msgs)
    assert len(out) == 2 and out[0]["role"] == "system"
    assert "exec_in_kali" in out[0]["content"]
    assert "uid=0" in out[0]["content"]


# ---------- loop integration: pairing ----------

def _coach(autonomy=4, use_tools=True):
    c = FakeClient()
    coach = SessionCoach(1, c, {"coach": {}, "llm": {"use_tools": use_tools}})
    coach.state.state = "active"
    coach.state.autonomy_level = autonomy
    coach.ctx = c.ctx
    return coach, c


async def test_tool_calls_dispatch_and_pair_results_in_history():
    coach, _c = _coach(autonomy=4)
    calls = [_call("exec_in_kali", {"command": "whoami"}, cid="c1"),
             _call("submit_flag", {"value": "pentrAIn{x}"}, cid="c2")]
    coach.llm = FakeLlm(
        tool_calls=calls,
        actions=[{"type": "exec_in_kali", "command": "whoami", "_call_id": "c1"},
                 {"type": "submit_flag", "value": "pentrAIn{x}", "_call_id": "c2"}])
    await coach._llm_turn("ctx")
    hist = coach._history
    asst = hist[-3]
    assert asst["role"] == "assistant" and asst["tool_calls"] == calls
    replies = hist[-2:]
    assert all(m["role"] == "tool" for m in replies)
    assert {m["tool_call_id"] for m in replies} == {"c1", "c2"}


async def test_denied_tool_call_still_gets_a_result():
    coach, _c = _coach(autonomy=2)   # exec denied at level 2
    calls = [_call("exec_in_kali", {"command": "id"}, cid="c1")]
    coach.llm = FakeLlm(
        tool_calls=calls,
        actions=[{"type": "exec_in_kali", "command": "id", "_call_id": "c1"}])
    await coach._llm_turn("ctx")
    tool_msg = coach._history[-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"
    assert "denied" in tool_msg["content"]


async def test_tools_disabled_turn_sends_plain_history_and_no_tools():
    coach, _c = _coach(use_tools=False)
    # pre-existing tool history must not leak onto a non-tools wire
    coach._history = [{"role": "assistant", "content": "earlier",
                       "tool_calls": [_call("none", {"reason": "x"})]},
                      {"role": "tool", "tool_call_id": "c1", "content": "r"}]
    fake = FakeLlm(actions=[{"type": "send_chat", "content": "hi"}])
    coach.llm = fake
    await coach._llm_turn("ctx")
    sent = fake.calls[0]
    assert fake.kwargs[0].get("tools") is None
    assert all(m.get("role") != "tool" for m in sent)
    assert all("tool_calls" not in m for m in sent)


async def test_tools_enabled_sends_schemas_to_llm():
    coach, _c = _coach(use_tools=True)
    fake = FakeLlm(actions=[{"type": "none"}])
    coach.llm = fake
    await coach._llm_turn("ctx")
    assert fake.kwargs[0]["tools"] == TOOLS


# ---------- llm.chat normalization (plain path) ----------

def _llm(handler) -> LlmClient:
    c = LlmClient("http://llm", "key", "model")
    c._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://llm")
    return c


async def test_chat_extracts_tool_calls_from_plain_response():
    def handler(req):
        import json as j
        body = j.loads(req.content)
        assert "tools" in body and body["tool_choice"] == "auto"
        return httpx.Response(200, json={
            "choices": [{"message": {
                "content": None,
                "tool_calls": [_call("exec_in_kali", {"command": "id"})]}}],
            "usage": {"total_tokens": 3}})

    resp = await _llm(handler).chat([{"role": "user", "content": "x"}],
                                    tools=TOOLS)
    assert resp["actions"][0]["type"] == "exec_in_kali"
    assert resp["tool_calls"] and resp["content"] == ""


async def test_chat_falls_back_when_endpoint_rejects_tools():
    seen: list[dict] = []

    def handler(req):
        import json as j
        body = j.loads(req.content)
        seen.append(body)
        if "tools" in body:
            return httpx.Response(400, text="tools not supported")
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"actions":[{"type":"none"}]}'}}],
            "usage": {"total_tokens": 1}})

    llm = _llm(handler)
    resp = await llm.chat([{"role": "user", "content": "x"}], tools=TOOLS)
    assert resp["actions"] == [{"type": "none"}]
    assert len(seen) == 2 and "tools" not in seen[1]
    assert seen[1]["response_format"] == {"type": "json_object"}
    assert "no_tools" in llm._compat
    # learned compat: next call skips tools from the start
    await llm.chat([{"role": "user", "content": "y"}], tools=TOOLS)
    assert "tools" not in seen[2]


async def test_structural_400_learns_fold_not_no_tools():
    """A jinja/history-structure rejection must NOT poison tools support —
    folding the history is the fix, not dropping tools."""
    seen: list[dict] = []

    def handler(req):
        import json as j
        body = j.loads(req.content)
        seen.append(body)
        if len(body["messages"]) > 2:
            return httpx.Response(
                400, text='Error rendering prompt with jinja template: '
                          '"No user query found in messages."')
        return httpx.Response(200, json={
            "choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {
                    "name": "none", "arguments": '{"reason":"ok"}'}}]}}],
            "usage": {}})

    msgs = [{"role": "system", "content": "s"},
            {"role": "assistant", "content": "old welcome"},
            {"role": "user", "content": "x"}]
    llm = _llm(handler)
    resp = await llm.chat(msgs, tools=TOOLS)
    assert resp["actions"][0]["type"] == "none"
    assert "fold" in llm._compat and "no_tools" not in llm._compat
    # retried request: still carries tools, history folded into system
    assert "tools" in seen[-1]
    assert len(seen[-1]["messages"]) == 2
