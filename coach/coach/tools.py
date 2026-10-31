"""Native tool-calling contract for the coach LLM — the single source of truth
for coach actions. tool_calls are normalized into the same action dicts the
JSON-mode contract produced, so dispatch/tests stay unchanged.
"""
from __future__ import annotations

import json

import structlog

log = structlog.get_logger(__name__)

# ---------- tool schema (single source of truth) ----------

def _fn(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props,
                       "required": required}}}


_str = lambda d: {"type": "string", "description": d}

TOOLS: list[dict] = [
    _fn("send_chat", "Send a markdown message to the trainee chat.",
        {"content": _str("markdown text")}, ["content"]),
    _fn("offer_hint", "Offer a hint at a specific escalation level.",
        {"content": _str("hint text"),
         "level": {"type": "integer", "minimum": 1, "maximum": 3}},
        ["content"]),
    _fn("suggest_command",
        "Suggest a shell command the trainee can confirm or reject.",
        {"command": _str("single POSIX shell line"),
         "why": _str("one short reason")}, ["command"]),
    _fn("exec_in_kali",
        "Execute a shell command on the trainee's Kali machine (autonomy 4).",
        {"command": _str("single POSIX shell line")}, ["command"]),
    _fn("submit_flag",
        "Submit a flag value literally seen in command output (pentrAIn{...}).",
        {"value": _str("flag value")}, ["value"]),
    _fn("check_flag",
        "Ask the server to verify a state/command-kind flag from FLAGS.",
        {"flag_key": _str("flag key")}, ["flag_key"]),
    _fn("mark_checkpoint",
        "Mark a quest checkpoint as reached (id from CHECKPOINTS_OPEN).",
        {"checkpoint_id": _str("checkpoint id")}, ["checkpoint_id"]),
    _fn("capture_screen",
        "Request a fresh screenshot description of the Kali desktop.", {}, []),
    _fn("none",
        "Stay silent; attach a private note kept as your working memory.",
        {"reason": _str("short private note")}, ["reason"]),
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}

# which tools may be *offered* at which autonomy level — don't let the model
# pick an action the gate will refuse anyway, and on takeover don't offer
# suggest_command at all (its confirm-chip can never be clicked in auto mode)
_LEVEL_TOOLS = {
    1: {"send_chat", "offer_hint", "capture_screen", "none"},
    2: {"send_chat", "offer_hint", "mark_checkpoint", "capture_screen", "none"},
    3: {"send_chat", "offer_hint", "suggest_command", "mark_checkpoint",
        "capture_screen", "none"},
    4: {"send_chat", "offer_hint", "exec_in_kali", "submit_flag", "check_flag",
        "mark_checkpoint", "capture_screen", "none"},
}


def tools_for_level(level: int) -> list[dict]:
    allowed = _LEVEL_TOOLS.get(level, _LEVEL_TOOLS[1])
    return [t for t in TOOLS if t["function"]["name"] in allowed]


# ---------- normalization ----------

def call_to_action(call: dict) -> dict | None:
    """One OpenAI tool_call → action dict, or None when unusable."""
    fn = call.get("function") or {}
    name = fn.get("name")
    if name not in TOOL_NAMES:
        return None
    raw = fn.get("arguments") or "{}"
    try:
        args = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(args, dict):
            return None
    except (json.JSONDecodeError, TypeError):
        return None
    action = {"type": name, **args}
    if call.get("id"):
        action["_call_id"] = call["id"]   # pairing key for the tool reply
    return action


def calls_to_actions(message: dict) -> list[dict]:
    """Normalize a response message into ordered action dicts.

    - content + tool_calls → send_chat action first (narration before work)
    - content only → [{"type":"send_chat", ...}]
    - empty + no calls → [{"type":"none"}]
    """
    actions: list[dict] = []
    content = (message.get("content") or "").strip()
    calls = message.get("tool_calls") or []
    if content and calls:
        actions.append({"type": "send_chat", "content": content[:2000]})
    for call in calls:
        a = call_to_action(call)
        if a is not None:
            actions.append(a)
        else:
            log.warning("dropping unusable tool_call",
                        name=(call.get("function") or {}).get("name"))
    if actions:
        return actions
    if content:
        return [{"type": "send_chat", "content": content[:2000]}]
    return [{"type": "none"}]


# ---------- history shaping ----------

def wire_history(msgs: list[dict], tools_active: bool) -> list[dict]:
    """History as sent on the wire. With tools inactive, `tool` messages and
    `assistant.tool_calls` must not reach a non-tools request (some templates
    reject tool roles there) — chat content stays, results live on via the
    persisted action_report messages."""
    if tools_active:
        out = list(msgs)
    else:
        out = []
        for m in msgs:
            if m.get("role") == "tool":
                continue
            m = dict(m)
            m.pop("tool_calls", None)
            out.append(m)
    # template compat: several chat templates (LM Studio llama.cpp jinja,
    # some MLX builds) require the FIRST non-system message to be a user
    # turn — a seeded assistant welcome at index 0 makes them 400 with
    # "No user query found". Leading assistant/tool entries are pure
    # context loss, never a pairing violation.
    while out and out[0].get("role") in ("assistant", "tool"):
        out.pop(0)
    return out


def trim_history(msgs: list[dict], cap: int) -> list[dict]:
    """Apply HISTORY_CAP without leaving orphan `tool` messages: a tool reply
    without its assistant.tool_calls parent breaks strict templates."""
    msgs = list(msgs)[-cap:] if cap else list(msgs)
    while msgs and msgs[0].get("role") == "tool":
        msgs.pop(0)
    return msgs
