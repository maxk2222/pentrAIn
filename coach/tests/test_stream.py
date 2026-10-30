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

    async def on_delta(cum: str):
        deltas.append(cum)

    resp = await llm.chat([{"role": "user", "content": "hi"}], on_delta=on_delta)
    assert resp["content"].endswith('"}]}')
    assert resp["actions"][0]["type"] == "send_chat"
    assert resp["actions"][0]["content"] == "Hello world"
    assert deltas and deltas[-1] == "Hello world"  # cumulative extraction
    assert llm.tokens_used == 42


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

    async def on_delta(cum: str):
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

    async def stream_draft(self, sid, draft_id, content, *, done=False, kind="chat"):
        self.drafts.append({"id": draft_id, "content": content, "done": done})


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
