# ADR 5: Coach reaction model — silence by default, three-path event routing

## Status
Accepted

## Context
The coach receives every event on the backend bus (telemetry commands, exit codes,
heartbeats, session state, flags, chat). Naively wiring events → LLM turns produces a
coach that comments on every command — noise, cost, and a worse teacher. A coach
must instead speak only when speaking helps.

## Decision
Route events along three strict paths inside `SessionCoach`:

1. **Telemetry path (silent)** — `command`/`command_result` events update local
   state (ring buffer, exit codes, checkpoint matcher) and `last_activity_ts`.
   They NEVER trigger an LLM turn. Checkpoint hits emit a cheap template ack.
2. **Signal path (reactive)** — trainee chat → debounced (1.5 s) direct LLM answer;
   flag submit → template ack; suggest-command confirm/reject → progress signal.
   No batching of user intent beyond debounce.
3. **Reflection path (proactive)** — a wall-clock timer every `reflect_interval_s`
   (independent of event volume — a busy user cannot starve it) evaluates `Policy`.
   The policy only grants speech for *stuck > threshold*, *idle too long*, or
   escalation stages, is throttled by a min-gap, and backs off exponentially after
   3 proactive messages without progress (`proactive_streak`).

Proactive output is tagged `kind=nudge` so the UI can style it distinctly; the
LLM is instructed that `{"type":"none"}` is the expected answer when things are
going fine. `none` reasons are kept as working notes for future turns.

## Consequences
- Command floods cost zero tokens; a user who never gets stuck may only ever see
  the welcome message, checkpoint acks, and their own answered questions.
- LLM turns carry a rolling 14-message history (seeded from the NEWEST persisted
  chat on attach), so the coach doesn't repeat itself across restarts.
- `capture_screen` feeds a configured `llm.vision_model` and lands in state as a
  text description — cheap for text-only coach models. Rate-limited to 30 s.
- Coach-issued `exec_in_kali` commands are echoed back through telemetry; they
  are matched (prefix + 20 s window) and marked `from_coach` so the coach's own
  activity never masquerades as trainee progress.
- Stuck/idle clocks seed from the most recent real signal (`started_at`,
  `ready_at`, last telemetry ts) on attach — a re-attach neither panics
  ("stuck since epoch") nor amnesties a genuinely stuck session.
- Settings changes propagate to live coaches via `apply_cfg` (policy knobs,
  killswitch, LLM client rebuild on endpoint change).
- LLM turns stream drafts to the UI: `chat(on_delta=)` extracts the first
  action's `content` string from partial JSON over SSE and relays it via
  `POST /api/coach/stream` → `coach_stream` WS events (cumulative text, ~120 ms
  throttle, never persisted). The first real message of the turn carries
  `meta.draft_id` so the frontend swaps the draft bubble atomically; a `done`
  signal cleans up turns that end without a visible message. Endpoints without
  SSE fall back to a plain completion — a mid-stream failure raises instead of
  silently retrying (the draft is already half-visible).
