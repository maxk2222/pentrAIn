"""Reasoning/think control: request-body fields + think-block stripping."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.llm import LlmClient, _fold_history, parse_actions


class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._p


async def _captured_body(client: LlmClient) -> dict:
    captured = {}

    async def fake_post(path, json=None):
        captured.update(json or {})
        return _Resp({"choices": [{"message": {"content": "x"}}]})

    client._client.post = fake_post
    await client.chat([{"role": "user", "content": "hi"}], json_mode=False)
    return captured


async def test_reasoning_off_sends_enable_thinking_false():
    c = LlmClient("http://x/v1", "", "m", reasoning=False)
    body = await _captured_body(c)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in body


async def test_reasoning_on_sends_effort():
    c = LlmClient("http://x/v1", "", "m", reasoning=True, reasoning_effort="high")
    body = await _captured_body(c)
    assert body["reasoning_effort"] == "high"
    assert "chat_template_kwargs" not in body


async def test_reasoning_default_no_fields():
    c = LlmClient("http://x/v1", "", "m")
    body = await _captured_body(c)
    assert "reasoning_effort" not in body and "chat_template_kwargs" not in body


def test_parse_strips_closed_think_block():
    raw = '<think>let me think about nmap flags…</think>{"actions":[{"type":"send_chat","content":"hi"}]}'
    assert parse_actions(raw) == [{"type": "send_chat", "content": "hi"}]


def test_parse_strips_unterminated_think_block():
    raw = '{"actions":[{"type":"none"}]}'  # sanity first
    assert parse_actions(raw)[0]["type"] == "none"
    out = parse_actions("<think>trail off with no close")
    assert out[0]["type"] == "none"
    assert out[0]["reason"] == "response was only a think block"


def test_fold_history_keeps_context_in_system():
    msgs = [{"role": "system", "content": "SYS"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"}]
    out = _fold_history(msgs)
    assert out[0]["role"] == "system" and "SYS" in out[0]["content"]
    assert "Trainee: q1" in out[0]["content"] and "Coach: a1" in out[0]["content"]
    assert out[1] == {"role": "user", "content": "q2"}
    assert len(out) == 2


async def test_chat_folds_on_template_400():
    c = LlmClient("http://x/v1", "", "m")
    bodies = []

    async def fake_post(path, json=None):
        bodies.append(dict(json or {}))
        if len(bodies) == 1:
            return _Resp({"error": "jinja: No user query found"}, 400)
        return _Resp({"choices": [{"message": {"content": "ok"}}]})

    c._client.post = fake_post
    r = await c.chat([{"role": "system", "content": "S"},
                      {"role": "assistant", "content": "old"},
                      {"role": "user", "content": "hi"}], json_mode=False)
    assert r["content"] == "ok"
    assert len(bodies[1]["messages"]) == 2            # retried folded
    assert bodies[1]["messages"][1]["role"] == "user"


def test_think_block_never_leaks_to_chat_fallback():
    raw = "<think>secret chain</think>not-json prose"
    out = parse_actions(raw)
    assert out[0]["type"] == "send_chat"
    assert out[0]["content"] == "not-json prose"
    assert "secret" not in out[0]["content"]


async def test_chat_returns_latency_and_usage():
    c = LlmClient("http://x/v1", "", "m")

    async def fake_post(path, json=None):
        return _Resp({"choices": [{"message": {"content": "ok"}}],
                      "usage": {"prompt_tokens": 3, "completion_tokens": 2,
                                "total_tokens": 5}})

    c._client.post = fake_post
    r = await c.chat([{"role": "user", "content": "hi"}], json_mode=False)
    assert r["usage"]["total_tokens"] == 5
    assert isinstance(r["latency_ms"], int) and r["latency_ms"] >= 0


async def test_report_llm_usage_posts_row():
    from coach.client import BackendClient
    sent = {}

    class _Cfg:
        backend_url = "http://be"
        coach_service_token = "t"
        backend_ws_url = "ws://be/ws"

    import coach.client as cc
    old = cc.get_config
    cc.get_config = lambda: _Cfg()
    try:
        cl = BackendClient()
        async def fake_post(path, body=None):
            sent["path"], sent["body"] = path, body
            return {}
        cl._post = fake_post
        await cl.report_llm_usage(7, "m1", "chat",
                                  {"total_tokens": 5, "prompt_tokens": 3}, 42)
        assert sent["path"] == "/api/coach/llm-usage"
        assert sent["body"]["total_tokens"] == 5 and sent["body"]["latency_ms"] == 42
        await cl.close()
    finally:
        cc.get_config = old
