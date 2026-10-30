"""Reasoning/think control: request-body fields + think-block stripping."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.llm import LlmClient, parse_actions


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._p = payload
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


def test_think_block_never_leaks_to_chat_fallback():
    raw = "<think>secret chain</think>not-json prose"
    out = parse_actions(raw)
    assert out[0]["type"] == "send_chat"
    assert out[0]["content"] == "not-json prose"
    assert "secret" not in out[0]["content"]
