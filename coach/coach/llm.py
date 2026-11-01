"""LLM client: any OpenAI-compatible chat endpoint (Ollama /v1, vLLM, LM Studio, gateways).

Primary contract is native tool calling (coach/tools.py schemas); endpoints
without tool support fall back to the JSON action list contract:
  {"actions":[{"type":"send_chat","content":"..."},
              {"type":"exec_in_kali","command":"..."},
              {"type":"none","reason":"..."}]}
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable

import httpx
import structlog

from .tools import calls_to_actions

log = structlog.get_logger(__name__)

ALLOWED_ACTIONS = {
    "send_chat", "offer_hint", "suggest_command", "exec_in_kali", "type_in_pane",
    "submit_flag", "check_flag", "mark_checkpoint", "capture_screen", "none",
    "spawn_agent", "collect_agent", "agent_status", "kill_agent",
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
        # learned endpoint quirks — once a fallback succeeded we skip straight
        # to it instead of paying a failed-request round-trip on every turn
        self._compat: set[str] = set()
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=httpx.Timeout(timeout_s, connect=15.0),
        )
        self.tokens_used = 0

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(self, messages: list[dict], *, json_mode: bool = True,
                   tools: list[dict] | None = None,
                   model: str | None = None,
                   on_delta: Callable[[str, str], Awaitable[None]] | None = None
                   ) -> dict:
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
        if tools and "no_tools" not in self._compat:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        elif json_mode:
            body["response_format"] = {"type": "json_object"}
        if "fold" in self._compat and len(body["messages"]) > 2:
            body["messages"] = _fold_history(body["messages"])
        if "no_response_format" in self._compat:
            body.pop("response_format", None)
        started = time.monotonic()
        if on_delta is not None:
            resp = await self._chat_stream(body, on_delta)
            if resp is not None:
                resp["latency_ms"] = int((time.monotonic() - started) * 1000)
                resp["usage"] = resp["raw"].get("usage") or {}
                return resp
            # endpoint refused/broke the stream before any token — plain call
        r = await self._client.post("/chat/completions", json=body)
        for _ in range(3):
            if r.status_code < 400:
                break
            err = (r.text or "")[:400].lower()
            structural = any(k in err for k in (
                "template", "jinja", "user query", "tool_call",
                "tool role", "message")) and r.status_code == 400
            if structural and len(body["messages"]) > 2:
                # exotic chat templates (some MLX builds) require the first
                # non-system message to be a user turn — an assistant message
                # earlier in history breaks jinja rendering. Fold history into
                # the system prompt and retry once.
                body["messages"] = _fold_history(body["messages"])
                self._compat.add("fold")
            elif "tools" in body:
                # endpoint rejects native tools — drop to the JSON contract
                body.pop("tools", None)
                body.pop("tool_choice", None)
                body["response_format"] = {"type": "json_object"}
                self._compat.add("no_tools")
            elif "response_format" in body:
                # some endpoints reject response_format — retry without
                body.pop("response_format", None)
                self._compat.add("no_response_format")
            elif r.status_code == 400 and len(body["messages"]) > 2:
                body["messages"] = _fold_history(body["messages"])
                self._compat.add("fold")
            else:
                break
            r = await self._client.post("/chat/completions", json=body)
        if r.status_code >= 400:
            raise LlmError(f"llm {r.status_code}: {r.text[:300]}")
        try:
            data = r.json()
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            reasoning = message.get("reasoning_content") or ""
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            raise LlmError(f"llm malformed response ({type(e).__name__}): {r.text[:200]}") from e
        # think blocks embedded in content → move to the reasoning channel,
        # never let them leak into a trainee-facing message
        content, think = _split_think(content)
        reasoning = (reasoning + "\n" + think).strip()
        usage = data.get("usage") or {}
        if usage:
            self.tokens_used += int(usage.get("total_tokens", 0))
        calls = message.get("tool_calls") or []
        actions = (calls_to_actions(message) if calls
                   else parse_actions(content))
        return {"content": content, "actions": actions, "tool_calls": calls,
                "raw": data, "usage": usage, "reasoning": reasoning,
                "latency_ms": int((time.monotonic() - started) * 1000)}

    async def _chat_stream(self, body: dict,
                           on_delta: Callable[[str, str], Awaitable[None]]
                           ) -> dict | None:
        """SSE stream from an OpenAI-compatible endpoint. Returns None when the
        stream failed BEFORE any token arrived (caller falls back to a plain
        request); raises LlmError when it broke mid-generation — retrying
        would double-report a turn whose draft is already half-visible.

        on_delta(answer, reasoning) receives CUMULATIVE strings — reasoning
        from delta.reasoning_content (LM Studio/vLLM) plus inline <think>
        blocks split out of content."""
        full = ""
        reasoning_full = ""
        calls_acc: dict[int, dict] = {}
        usage: dict = {}
        last_pushed = 0
        last_reason = 0
        last_answer = ""
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
                    delta = (choices[0].get("delta") or {}) if choices else {}
                    for tc in delta.get("tool_calls") or []:
                        acc = calls_acc.setdefault(
                            int(tc.get("index") or 0),
                            {"id": None, "type": "function",
                             "function": {"name": "", "arguments": ""}})
                        if tc.get("id"):
                            acc["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            acc["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            acc["function"]["arguments"] += fn["arguments"]
                    if rc := delta.get("reasoning_content"):
                        reasoning_full += rc
                    piece = delta.get("content")
                    if piece:
                        full += piece
                    # reasoning visible so far = dedicated channel + any think
                    # segments embedded in the content stream
                    _, think_now = _split_think(full)
                    reasoning_now = (reasoning_full + "\n" + think_now).strip()
                    if reasoning_now and len(reasoning_now) > last_reason:
                        last_reason = len(reasoning_now)
                        await on_delta(last_answer, reasoning_now)
                    if not piece:
                        # a send_chat tool call streams its chat text inside
                        # `arguments` — decode it for the live draft
                        extracted = _stream_send_chat_arg(calls_acc)
                        if extracted and len(extracted) > last_pushed:
                            last_pushed = len(extracted)
                            last_answer = extracted
                            await on_delta(extracted, reasoning_now)
                        continue
                    extracted = _extract_stream_content(full)
                    if extracted and len(extracted) > last_pushed:
                        last_pushed = len(extracted)
                        last_answer = extracted
                        await on_delta(extracted, reasoning_now)
        except (TimeoutError, httpx.HTTPError, OSError) as e:
            if full or calls_acc or reasoning_full:
                raise LlmError(f"llm stream broke mid-response: {e}") from e
            return None
        calls = [calls_acc[i] for i in sorted(calls_acc)]
        if not full and not calls:
            return None
        if usage:
            self.tokens_used += int(usage.get("total_tokens", 0))
        content, think = _split_think(full)
        reasoning = (reasoning_full + "\n" + think).strip()
        message = {"content": content, "tool_calls": calls}
        actions = calls_to_actions(message) if calls else parse_actions(content)
        return {"content": content, "actions": actions, "tool_calls": calls,
                "reasoning": reasoning, "raw": {"usage": usage}}


def _split_think(raw: str) -> tuple[str, str]:
    """Split `<think>…</think>` segments out of a (possibly partial) text blob.
    Returns (answer, reasoning) — an unterminated trailing think block counts
    as reasoning-in-progress, which is exactly what streams produce."""
    answer_parts: list[str] = []
    think_parts: list[str] = []
    rest = raw
    while True:
        m = re.search(r"<think\b[^>]*>", rest, re.IGNORECASE)
        if not m:
            answer_parts.append(rest)
            break
        answer_parts.append(rest[:m.start()])
        rest = rest[m.end():]
        end = re.search(r"</think\s*>", rest, re.IGNORECASE)
        if not end:
            think_parts.append(rest)
            break
        think_parts.append(rest[:end.start()])
        rest = rest[end.end():]
    return "".join(answer_parts), "\n".join(t.strip() for t in think_parts if t.strip())


def _fold_history(messages: list[dict]) -> list[dict]:
    """Collapse a [system, ...history..., user] list into [system', user] —
    prior turns serialized as text inside the system prompt. Keeps context
    while satisfying chat templates that demand a user-first structure."""
    system_parts: list[str] = []
    history_lines: list[str] = []
    last_user: dict | None = None
    for m in messages:
        role, content = m.get("role"), m.get("content")
        if role == "system":
            system_parts.append(str(content))
        elif role == "user" and m is messages[-1]:
            last_user = m
        elif role == "tool":
            history_lines.append(f"Coach tool result: {content}")
        elif role in ("user", "assistant"):
            tag = "Trainee" if role == "user" else "Coach"
            for call in m.get("tool_calls") or []:
                fn = call.get("function") or {}
                history_lines.append(
                    f"Coach tool call {fn.get('name')}({fn.get('arguments')})")
            if content:
                history_lines.append(f"{tag}: {content}")
    if history_lines:
        system_parts.append(
            "CONVERSATION SO FAR (context only — continue from here):\n"
            + "\n".join(history_lines))
    folded = [{"role": "system", "content": "\n\n".join(p for p in system_parts if p)}]
    folded.append(last_user or {"role": "user", "content": "continue"})
    return folded


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/",
            "b": "\b", "f": "\f"}


def _stream_send_chat_arg(calls_acc: dict[int, dict]) -> str | None:
    """While tool_calls stream, the trainee-visible text lives inside the
    send_chat call's `arguments` JSON — decode the partial `content` value
    with the same tolerant extractor used for JSON-mode drafts."""
    for i in sorted(calls_acc):
        acc = calls_acc[i]
        if acc["function"]["name"] != "send_chat":
            continue
        return _extract_stream_content(acc["function"]["arguments"])
    return None


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
        # prose + JSON mix or trailing garbage — decode the first complete
        # JSON object at any '{' position instead of parroting the raw blob
        data = None
        dec = json.JSONDecoder()
        for m in re.finditer(r"\{", text):
            try:
                data, _end = dec.raw_decode(text, m.start())
                break
            except json.JSONDecodeError:
                continue
        if data is None:
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
