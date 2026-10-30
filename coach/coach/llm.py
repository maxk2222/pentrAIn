"""LLM client: any OpenAI-compatible chat endpoint (Ollama /v1, vLLM, LM Studio, gateways).

Responses are asked for as a JSON action list — robust even on abliterated
fine-tunes with weak native tool-calling support:
  {"actions":[{"type":"send_chat","content":"..."},
              {"type":"suggest_command","command":"...","why":"..."},
              {"type":"exec_in_kali","command":"..."},
              {"type":"mark_checkpoint","checkpoint_id":"c1"},
              {"type":"none","reason":"..."}]}
"""
from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

import httpx
import structlog

log = structlog.get_logger(__name__)

ALLOWED_ACTIONS = {
    "send_chat", "offer_hint", "suggest_command", "exec_in_kali",
    "mark_checkpoint", "capture_screen", "none",
}


class LlmError(RuntimeError):
    pass


class LlmClient:
    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.4, timeout_s: int = 120,
                 reasoning: bool = True, reasoning_effort: str | None = None):
        self.model = model
        self.temperature = temperature
        self.reasoning = reasoning
        self.reasoning_effort = reasoning_effort
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=httpx.Timeout(timeout_s, connect=15.0),
        )
        self.tokens_used = 0

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(self, messages: list[dict], *, json_mode: bool = True,
                   model: str | None = None,
                   on_delta: Callable[[str], Awaitable[None]] | None = None) -> dict:
        body: dict = {
            "model": model or self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        # reasoning control — endpoint flavors differ, so use the two dominant
        # conventions: chat_template_kwargs.enable_thinking (Qwen3/vLLM chat
        # template switch) and reasoning_effort (OpenAI-compat field). Servers
        # that don't know a key ignore it; failures surface in the UI test.
        if not self.reasoning:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        elif self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if on_delta is not None:
            resp = await self._chat_stream(body, on_delta)
            if resp is not None:
                return resp
            # endpoint refused/broke the stream before any token — plain call
        r = await self._client.post("/chat/completions", json=body)
        if r.status_code >= 400:
            # some endpoints reject response_format — retry without
            if json_mode and r.status_code == 400:
                body.pop("response_format", None)
                r = await self._client.post("/chat/completions", json=body)
            if r.status_code >= 400:
                raise LlmError(f"llm {r.status_code}: {r.text[:300]}")
        try:
            data = r.json()
            content = data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            raise LlmError(f"llm malformed response ({type(e).__name__}): {r.text[:200]}") from e
        if usage := data.get("usage"):
            self.tokens_used += int(usage.get("total_tokens", 0))
        return {"content": content, "actions": parse_actions(content), "raw": data}

    async def _chat_stream(self, body: dict,
                           on_delta: Callable[[str], Awaitable[None]]) -> dict | None:
        """SSE stream from an OpenAI-compatible endpoint. Returns None when the
        stream failed BEFORE any token arrived (caller falls back to a plain
        request); raises LlmError when it broke mid-generation — retrying
        would double-report a turn whose draft is already half-visible."""
        full = ""
        usage: dict = {}
        last_pushed = 0
        sbody = dict(body, stream=True,
                     stream_options={"include_usage": True})
        try:
            async with self._client.stream(
                    "POST", "/chat/completions", json=sbody) as r:
                if r.status_code >= 400:
                    await r.aread()
                    return None
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if u := chunk.get("usage"):
                        usage = u
                    choices = chunk.get("choices") or []
                    piece = (choices[0].get("delta") or {}).get("content") if choices else None
                    if not piece:
                        continue
                    full += piece
                    extracted = _extract_stream_content(full)
                    if extracted and len(extracted) > last_pushed:
                        last_pushed = len(extracted)
                        await on_delta(extracted)
        except (TimeoutError, httpx.HTTPError, OSError) as e:
            if full:
                raise LlmError(f"llm stream broke mid-response: {e}") from e
            return None
        if not full:
            return None
        if usage:
            self.tokens_used += int(usage.get("total_tokens", 0))
        return {"content": full, "actions": parse_actions(full),
                "raw": {"usage": usage}}


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/",
            "b": "\b", "f": "\f"}


def _extract_stream_content(raw: str) -> str | None:
    """Pull the first action's "content" string out of a PARTIAL JSON blob.
    The model emits {"actions":[{"type":"send_chat","content":"..."}...]} —
    while it is still writing, this returns the value decoded so far, or None
    once no content key exists yet. Tolerates unterminated strings."""
    m = re.search(r'"content"\s*:\s*"', raw)
    if not m:
        return None
    i = m.end()
    out: list[str] = []
    while i < len(raw):
        c = raw[i]
        if c == "\\":
            if i + 1 >= len(raw):
                break
            esc = raw[i + 1]
            if esc == "u" and i + 5 < len(raw):
                try:
                    out.append(chr(int(raw[i + 2:i + 6], 16)))
                except ValueError:
                    pass
                i += 6
            else:
                out.append(_ESCAPES.get(esc, esc))
                i += 2
        elif c == '"':
            break
        else:
            out.append(c)
            i += 1
    text = "".join(out)
    return text or None


def parse_actions(content: str) -> list[dict]:
    """Extract the action list from model output (tolerates markdown fences/prose)."""
    # strip thinking blocks first — chain-of-thought must never leak into chat
    text = re.sub(r"<think\b[^>]*>.*?</think>", "", content,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think\b[^>]*>.*$", "", text,
                  flags=re.DOTALL | re.IGNORECASE).strip()  # unterminated block
    if not text:
        return [{"type": "none", "reason": "response was only a think block"}]
    # strip code fences
    m = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    # find first {...} block if whole text isn't JSON
    if not text.startswith(("{", "[")):
        m = re.search(r"(\{.*\})", text, re.DOTALL)
        if m:
            text = m.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [{"type": "send_chat", "content": text[:1500]}]
    if isinstance(data, dict) and "actions" in data:
        data = data["actions"]
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return [{"type": "send_chat", "content": text[:1500]}]
    out = []
    for a in data:
        if isinstance(a, dict) and a.get("type") in ALLOWED_ACTIONS:
            out.append(a)
    return out or [{"type": "none", "reason": "no valid actions parsed"}]
