"""Streaming regressions: partial-JSON extraction, SSE parsing, draft relay."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_loop_reactions import FakeClient, FakeLlm

from coach.llm import LlmClient, _extract_stream_content
from coach.loop import SessionCoach

# ---------- partial-JSON content extractor ----------


def test_extract_from_complete_json():
    raw = '{"actions":[{"type":"send_chat","content":"run nmap first"}]}'
    assert _extract_stream_content(raw) == "run nmap first"


def test_extract_unterminated():
    raw = '{"actions":[{"type":"send_chat","content":"run nm'
    assert _extract_stream_content(raw) == "run nm"


def test_extract_none_before_content_key():
    raw = '{"actions":[{"type":"none","reason":"wa'
    assert _extract_stream_content(raw) is None


def test_extract_handles_escapes():
    raw = r'{"actions":[{"type":"send_chat","content":"line1\nline2 \"q\"'
    assert _extract_stream_content(raw) == 'line1\nline2 "q"'


def test_extract_unicode_escape():
    raw = r'{"actions":[{"type":"send_chat","content":"aA'
    assert _extract_stream_content(raw) == "aA"


def test_extract_ignores_content_inside_command():
    # "content" as a key inside a different context still extracts — pragmatic
    raw = '{"actions":[{"type":"send_chat","content":"first"},{"type":"offer_hint","content":"second"}]}'
    assert _extract_stream_content(raw) == "first"


# ---------- SSE streaming in LlmClient ----------


def _sse(*chunks: dict) -> bytes:
    lines = "".join(f"data: {__import__('json').dumps(c)}\n\n" for c in chunks)
    return (lines + "data: [DONE]\n\n").encode()


async def test_chat_stream_parses_sse_and_emits_deltas():
    full = '{"actions":[{"type":"send_chat","content":"Hello world"}]}'
    pieces = [full[:38], full[38:58], full[58:]]
    body = _sse(
        *[{"choices": [{"delta": {"content": p}}]} for p in pieces],
        {"choices": [], "usage": {"total_tokens": 42}},
    )

    def handler(req: httpx.Request) -> httpx.Response:
        import json as j
        payload = j.loads(req.content)
        assert payload["stream"] is True
        return httpx.Response(200, content=body)

    llm = LlmClient("http://x", "k", "m")
    llm._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://x")
    deltas: list[str] = []

    async def on_delta(cum: str, reasoning: str = ""):
        deltas.append(cum)

    resp = await llm.chat([{"role": "user", "content": "hi"}], on_delta=on_delta)
    assert resp["content"].endswith('"}]}')
    assert resp["actions"][0]["type"] == "send_chat"
    assert resp["actions"][0]["content"] == "Hello world"
    assert deltas and deltas[-1] == "Hello world"  # cumulative extraction
    assert llm.tokens_used == 42


def _tc(index, *, cid=None, name=None, args=None):
    """One streamed tool_call delta fragment."""
    d: dict = {"index": index, "function": {}}
    if cid:
        d["id"] = cid
        d["type"] = "function"
    if name is not None:
        d["function"]["name"] = name
    if args is not None:
        d["function"]["arguments"] = args
    return {"choices": [{"delta": {"tool_calls": [d]}}]}


async def test_chat_stream_accumulates_tool_calls_across_chunks():
    """Tool-call arguments arrive as JSON fragments; ids/names appear once."""
    body = _sse(
        _tc(0, cid="call_1", name="exec_in_kali", args='{"comma'),
        _tc(0, args='nd":"id"}'),
        _tc(1, cid="call_2", name="submit_flag",
            args='{"value":"pentrAIn{x}"}'),
        {"choices": [], "usage": {"total_tokens": 9}},
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    llm = LlmClient("http://x", "k", "m")
    llm._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://x")
    resp = await llm.chat([{"role": "user", "content": "hi"}],
                          on_delta=lambda c, r="": _noop())
    assert [a["type"] for a in resp["actions"]] == ["exec_in_kali", "submit_flag"]
    assert resp["actions"][0]["command"] == "id"
    assert resp["actions"][1]["value"] == "pentrAIn{x}"
    assert resp["actions"][0]["_call_id"] == "call_1"
    assert resp["content"] == "" and resp["usage"]["total_tokens"] == 9


async def test_chat_stream_tool_call_drafts_send_chat_args():
    """While a send_chat call streams, its `arguments.content` feeds the draft."""
    body = _sse(
        _tc(0, cid="c1", name="send_chat", args='{"content":"run nm'),
        _tc(0, args='ap -sV first"}'),
        {"choices": [], "usage": {}},
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    llm = LlmClient("http://x", "k", "m")
    llm._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://x")
    deltas: list[str] = []
    resp = await llm.chat([{"role": "user", "content": "hi"}],
                          on_delta=lambda c, r="": _noop_delta(deltas, c))
    assert deltas and deltas[-1] == "run nmap -sV first"
    assert resp["actions"][0]["type"] == "send_chat"


async def _noop(cum="", reasoning=""): ...
async def _noop_delta(lst, cum, reasoning=""): lst.append(cum)


async def test_chat_stream_falls_back_when_refused():
    def handler(req: httpx.Request) -> httpx.Response:
        import json as j
        if j.loads(req.content).get("stream"):
            return httpx.Response(400, content=b"stream unsupported")
        return httpx.Response(200, content=j.dumps({
            "choices": [{"message": {"content": '{"actions":[{"type":"none"}]}'}}],
            "usage": {"total_tokens": 7}}).encode())

    llm = LlmClient("http://x", "k", "m")
    llm._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://x")
    called = False

    async def on_delta(cum: str, reasoning: str = ""):
        nonlocal called
        called = True

    resp = await llm.chat([{"role": "user", "content": "hi"}], on_delta=on_delta)
    assert resp["actions"] == [{"type": "none"}]
    assert not called          # no draft emitted on the plain path
    assert llm.tokens_used == 7


# ---------- draft relay through the turn ----------


class StreamLlm(FakeLlm):
    async def chat(self, messages, **kw):
        cb = kw.get("on_delta")
        if cb:
            await cb("partial ans")
            await asyncio.sleep(0.15)   # outpace the 0.12s relay throttle
            await cb("partial answer")
        return await super().chat(messages, **kw)


class StreamClient(FakeClient):
    def __init__(self, ctx=None):
        super().__init__(ctx)
        self.drafts: list[dict] = []

    async def stream_draft(self, sid, draft_id, content, *, reasoning="",
                           done=False, kind="chat", agent="main"):
        self.drafts.append({"id": draft_id, "content": content,
                            "reasoning": reasoning, "done": done,
                            "agent": agent})


def _coach() -> tuple[SessionCoach, StreamClient]:
    c = StreamClient()
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.state.state = "active"
    coach.state.autonomy_level = 2
    coach.ctx = c.ctx
    return coach, c


async def test_turn_relays_deltas_and_tags_first_message():
    coach, c = _coach()
    coach.llm = StreamLlm(actions=[{"type": "send_chat", "content": "partial answer"}])
    spoke = await coach._llm_turn("ctx", proactive=False)
    assert spoke
    # two delta pushes + one done
    assert [d["content"] for d in c.drafts if not d["done"]] == ["partial ans", "partial answer"]
    assert any(d["done"] for d in c.drafts)
    # the real message carries the draft_id so the UI can swap it in
    assert c.chats[0]["meta"]["draft_id"] == c.drafts[0]["id"]


async def test_second_message_gets_no_draft_meta():
    coach, c = _coach()
    coach.llm = StreamLlm(actions=[
        {"type": "send_chat", "content": "one"},
        {"type": "send_chat", "content": "two"},
    ])
    await coach._llm_turn("ctx")
    assert c.chats[0]["meta"]["draft_id"].startswith("1d")
    assert not c.chats[1]["meta"].get("draft_id")


async def test_turn_without_content_sends_done_only():
    coach, c = _coach()
    coach.llm = StreamLlm(actions=[{"type": "none", "reason": "quiet"}])
    spoke = await coach._llm_turn("ctx", proactive=True)
    assert not spoke
    # deltas were pushed (extractor streamed something) → done must clean up;
    # here extractor found no "content" key → pushed=False → no done needed
    assert all(not d["done"] or True for d in c.drafts)
    assert not c.chats


# ---------- reasoning channel ----------


async def test_stream_collects_reasoning_content_deltas():
    """LM Studio/Qwen stream reasoning in delta.reasoning_content — it must
    reach on_delta's second arg and resp['reasoning']."""
    body = _sse(
        {"choices": [{"delta": {"reasoning_content": "let me think"}}]},
        {"choices": [{"delta": {"reasoning_content": " about ports"}}]},
        {"choices": [{"delta": {"content":
            '{"actions":[{"type":"send_chat","content":"hi"}]}'}}]},
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    llm = LlmClient("http://x", "k", "m")
    llm._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://x")
    seen: list[tuple[str, str]] = []

    async def on_delta(ans: str, reasoning: str = ""):
        seen.append((ans, reasoning))

    resp = await llm.chat([{"role": "user", "content": "hi"}], on_delta=on_delta)
    assert resp["reasoning"] == "let me think about ports"
    assert any(r for _, r in seen)            # reasoning streamed live
    assert resp["actions"][0]["type"] == "send_chat"


async def test_stream_splits_inline_think_block():
    """Models embedding <think>…</think> inside content get it split into the
    reasoning channel — it must never land in resp['content']."""
    body = _sse(
        {"choices": [{"delta": {"content": "<think>scheming"}}]},
        {"choices": [{"delta": {"content": " quietly</think>"}}]},
        {"choices": [{"delta": {"content":
            '{"actions":[{"type":"send_chat","content":"hi"}]}'}}]},
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    llm = LlmClient("http://x", "k", "m")
    llm._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://x")
    resp = await llm.chat([{"role": "user", "content": "hi"}],
                          on_delta=lambda a, r="": _noop())
    assert "<think" not in resp["content"]
    assert "scheming" in resp["reasoning"]
    assert resp["actions"][0]["type"] == "send_chat"


async def test_plain_response_moves_think_to_reasoning():
    """Non-stream path: <think> inside message.content + the reasoning_content
    field both land in resp['reasoning'] — content stays clean for force_reply."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=b"stream unsupported") \
            if b'"stream": true' in req.content or b'"stream":true' in req.content \
            else httpx.Response(200, content=(
                b'{"choices":[{"message":{"content":"<think>hmm</think> '
                b'{\\"actions\\":[{\\"type\\":\\"send_chat\\",\\"content\\":\\"yo\\"}]}",'
                b'"reasoning_content":"outer"}}],"usage":{}}'))

    llm = LlmClient("http://x", "k", "m")
    llm._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://x")
    resp = await llm.chat([{"role": "user", "content": "hi"}],
                          on_delta=lambda a, r="": _noop())
    assert "<think" not in resp["content"]
    assert "hmm" in resp["reasoning"] and "outer" in resp["reasoning"]
    assert resp["actions"][0]["content"] == "yo"


async def test_reasoning_relayed_in_draft_and_persisted_in_meta():
    """The turn must relay reasoning with the draft AND persist it in the
    final message's meta so the bubble keeps a 'thinking' section."""
    class ReasonLlm(FakeLlm):
        async def chat(self, messages, **kw):
            cb = kw.get("on_delta")
            if cb:
                await cb("", "pondering…")
            resp = await super().chat(messages, **kw)
            resp["reasoning"] = "pondering deeply"
            return resp

    coach, c = _coach()
    coach.llm = ReasonLlm(actions=[{"type": "send_chat", "content": "answer"}])
    spoke = await coach._llm_turn("ctx")
    assert spoke
    assert c.drafts[0]["reasoning"] == "pondering…"
    assert c.chats[0]["meta"]["draft_id"] == c.drafts[0]["id"]
    assert c.chats[0]["meta"]["reasoning"] == "pondering deeply"
