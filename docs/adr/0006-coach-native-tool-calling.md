# ADR-0006: Coach acts via native LLM tool calling

## Status
Accepted

## Context
The coach's action contract was a prompt-only JSON convention: the model had
to emit `{"actions":[...]}` as message text, and `llm.parse_actions` scraped
the object out of fences and prose. Live testing showed the failure class
this invites — the model posted raw action JSON *into* the chat, put a flag
submission inside `content` instead of `actions`, and schema drift between
the prompt text, `ALLOWED_ACTIONS`, and dispatch silently discarded valid
actions (`submit_flag`/`check_flag` were missing from the allowlist for a
while, so every correct submission attempt was dropped).

## Decision
Primary contract is **native tool calling** (`tools`/`tool_choice: "auto"` on
the chat-completions request). `coach/tools.py` is the single source of
truth: 9 function schemas (`send_chat`, `offer_hint`, `suggest_command`,
`exec_in_kali`, `submit_flag`, `check_flag`, `mark_checkpoint`,
`capture_screen`, `none`), plus normalization that maps `tool_calls` back
into the existing `{type, ...}` action dicts — dispatch, tests, and the
`{content, actions, usage}` seam in `LlmClient.chat()` stay unchanged.

Compatibility ladder per request (learned once in `_compat`, then skipped):
1. tools request → 2. retry without tools (`no_tools`, JSON mode) →
3. retry without `response_format` (`no_response_format`) →
4. folded-history retry (`fold`). `llm.use_tools` (Settings) disables tools
per turn without rebuilding the client.

Tool history lives in-memory beside the chat history: every assistant
`tool_calls` message is followed by one `role:"tool"` reply **per call** —
including denied/rejected calls — because strict chat templates reject
unpaired calls. Human-readable `action_report` chat messages continue to
carry results for the UI and for restart continuity; on restart only the
chat messages persist, so structured tool history is rebuilt best-effort.
`wire_history(tools_active)` strips `tool` messages and `tool_calls` keys
when a later turn falls back to JSON mode; `trim_history` trims without
leaving orphan tool replies.

Streaming keeps working on both paths: content deltas feed the draft as
before; a `send_chat` tool call streams its trainee-visible text inside
`arguments`, which the same tolerant partial-JSON extractor decodes for the
live draft. `reasoning_content` stays out of the user-visible channel.

## Consequences
- Schema drift is structurally impossible: one schema feeds the endpoint,
  normalization, and the allowlist (pinned by `test_tool_names_cover_all_allowed_actions`).
- Weak endpoints degrade gracefully to the JSON contract; the vision path
  (`json_mode=False`) is intentionally tools-free.
- Tool history is volatile by design — the durable record is the
  `action_report` stream, which doubles as the audit trail (ADR-0003).
