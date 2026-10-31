"""Regression tests for quality-review fixes in the coach service."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.llm import LlmClient, LlmError, parse_actions
from coach.loop import SessionCoach


class FakeClient:
    def __init__(self):
        self.chats: list[dict] = []

    async def send_chat(self, sid, content, *, kind="chat", meta=None):
        self.chats.append({"content": content, "kind": kind})
        return {}

    async def suggest_command(self, sid, command, why):
        return {}

    async def exec_in_kali(self, sid, command):
        return {"out": "ok"}

    async def mark_checkpoint(self, sid, cid):
        return {}

    async def report_llm_usage(self, sid, model, kind, usage, latency_ms):
        return {}

    async def send_activity(self, sid, text="", *, active=True):
        pass

    async def stream_draft(self, sid, draft_id, content, *, reasoning="",
                           done=False, kind="chat"):
        pass


class RecordingLlm:
    """Fake LlmClient that counts calls."""
    def __init__(self):
        self.calls = 0
        self.model = "recording"

    async def chat(self, messages, **_kw):
        self.calls += 1
        return {"content": "hi", "actions": [], "raw": {"usage": {"total_tokens": 5}}}


# ---------- malformed events ----------

async def test_handle_event_ignores_malformed_session_id():
    coach = SessionCoach(1, FakeClient(), {})
    # non-numeric session_id must not raise (used to crash via int("abc"))
    await coach._handle_event({"topic": "telemetry.1", "type": "telemetry",
                               "data": {"session_id": "abc", "kind": "command",
                                        "payload": {"command": "ls"}}})
    await coach._handle_event({"topic": "telemetry.1", "type": "telemetry",
                               "data": {"session_id": {"bad": "dict"}}})


# ---------- LLM response robustness ----------

def _llm(handler) -> LlmClient:
    c = LlmClient("http://llm", "key", "model")
    c._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://llm")
    return c


async def test_llm_malformed_response_raises_llmerror():
    def handler(req):
        return httpx.Response(200, json={"unexpected": "shape"})
    with pytest.raises(LlmError, match="malformed"):
        await _llm(handler).chat([{"role": "user", "content": "hi"}])


async def test_llm_non_json_body_raises_llmerror():
    def handler(req):
        return httpx.Response(200, text="<html>proxy error</html>")
    with pytest.raises(LlmError):
        await _llm(handler).chat([{"role": "user", "content": "hi"}])


async def test_llm_500_raises_llmerror():
    def handler(req):
        return httpx.Response(500, text="boom")
    with pytest.raises(LlmError):
        await _llm(handler).chat([{"role": "user", "content": "hi"}])


def test_parse_actions_fences_and_prose():
    actions = parse_actions('Sure! ```json\n{"actions":[{"type":"send_chat","content":"ok"}]}\n```')
    assert actions == [{"type": "send_chat", "content": "ok"}]
    # garbage input degrades to a chat action, never raises
    assert parse_actions("hello world")[0]["type"] == "send_chat"
    assert parse_actions("[1,2,3]")[0]["type"] == "none"


# ---------- daily token budget ----------

async def test_daily_token_budget_blocks_llm():
    usage = {"day": datetime.date.today().isoformat(), "tokens": 9999}
    c = FakeClient()
    coach = SessionCoach(1, c, {"llm": {"daily_token_budget": 100}}, usage=usage)
    fake = RecordingLlm()
    coach.llm = fake  # type: ignore[assignment]
    await coach._llm_turn("hello")
    assert fake.calls == 0                        # budget blocked the call
    assert any("token budget" in m["content"] for m in c.chats)
    # second turn does not re-warn
    c.chats.clear()
    await coach._llm_turn("hello again")
    assert c.chats == []


async def test_daily_budget_counts_usage_and_resets():
    usage = {"day": "2000-01-01", "tokens": 9999}   # stale day → resets
    c = FakeClient()
    coach = SessionCoach(1, c, {"llm": {"daily_token_budget": 10}}, usage=usage)
    fake = RecordingLlm()
    coach.llm = fake  # type: ignore[assignment]
    await coach._llm_turn("hello")
    assert fake.calls == 1
    assert usage["day"] == datetime.date.today().isoformat()
    assert usage["tokens"] == 5                    # 5 tokens from fake usage
