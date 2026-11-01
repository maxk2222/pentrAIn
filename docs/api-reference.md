# API reference

Base URL: `https://<pentrain-app>/api` — everything below is under that
prefix unless noted. Auth is a bearer token from `POST /auth/login`
(`Authorization: Bearer <token>`), except where marked.

> [!NOTE]
> Interactive exploration: FastAPI's generated OpenAPI UI lives at
> `/docs` on the backend (`http://<host>:8000/docs`).

## Auth & setup

| Method | Path | Notes |
|---|---|---|
| GET | `/setup/status` | `{completed, needs_setup}` — public |
| POST | `/auth/login` | `{password}` → `{token}`; **first call adopts the password** on a fresh install |
| POST | `/setup/complete` | `{updates: {...}}` — open only until an admin password exists, then bearer-gated (takeover guard) |
| GET | `/health` | `{ok, service}` — public |

## Settings

| Method | Path | Notes |
|---|---|---|
| GET | `/settings` | Full registry; secrets redacted to `********` |
| PATCH | `/settings` | `{updates: {key: value}}` — type-coerced against the registry; `********` echoes keep stored secrets |

Key registry: [configuration.md](configuration.md).

## Library

| Method | Path | Notes |
|---|---|---|
| GET | `/tracks` | Track cards: title, tier progress, quest counts |
| GET | `/quests` | All quests with lock state + `lock_reason` |
| GET | `/quests/{quest_id}` | Detail: briefing markdown, topology, flags (no values), hints w/ cost, scoring |
| GET | `/quests/{quest_id}/leaderboard` | Ranked attempts |
| GET | `/leaderboard` | Global leaderboard |
| POST | `/packs/sync` | Re-import `content/packs` into the DB |

## Sessions

| Method | Path | Notes |
|---|---|---|
| POST | `/sessions` | `{quest_id, autonomy_level?}` → 201 `{Session}`; aborts+replaces any active session |
| GET | `/sessions/active` | `{Session}` or `null` |
| GET | `/sessions/{id}` | Full session: state, flags progress, vmids, `kali_internet`, `subagents_enabled`, error |
| GET | `/sessions/{id}/log` | Deploy log `{log}` |
| POST | `/sessions/{id}/activate` | `ready → active` — starts the scoring clock |
| POST | `/sessions/{id}/reset` | `{hard: bool}` — snapshot rollback vs full redeploy |
| POST | `/sessions/{id}/abort` | Tear down the range |
| GET | `/sessions/{id}/flags` | Flag list w/ `solved` state — never the values |
| POST | `/sessions/{id}/flags` | `{value}` → `{correct, flag_id?}` |
| POST | `/sessions/{id}/flags/check` | `{flag_key}` — verify a `kind: command` flag on demand |
| POST | `/sessions/{id}/hints` | `{hint_id}` → reveals the hint, records the point cost |
| POST | `/sessions/{id}/assist` | `{kind: sheet|chat}` — records assistance-panel opt-ins for solve style |
| POST | `/sessions/{id}/autonomy` | `{level: 1-4}` — live coach level switch |
| POST | `/sessions/{id}/subagents` | `{enabled: bool}` — L4 worker toggle |
| POST | `/sessions/{id}/internet` | `{enabled: bool}` → `{enabled, ip?}` — hot-plug Kali `net1` |
| POST | `/sessions/{id}/actions/{action_id}/confirm` | `{accept: bool}` — accept/dismiss a `suggest_command` chip (L3) |
| GET | `/sessions/{id}/console` | Mint a PVE noVNC ticket `{ticket, port, vmid, host}` |
| GET | `/sessions/{id}/console/clipboard` | Read guest clipboard via QGA |
| GET | `/sessions/{id}/metrics` | Live per-VM cpu/mem/balloon gauges |
| GET | `/sessions/{id}/metrics/history` | Time series for the session |
| GET | `/sessions/{id}/live` | Live aggregate for the stats overlay |
| GET | `/sessions/{id}/telemetry` | Recent telemetry events |

### Session object (main fields)

```json
{
  "id": 7, "quest_id": "linux-t1-first-foothold",
  "state": "active", "autonomy_level": 2, "subagents_enabled": false,
  "kali_internet": false, "kali_vmid": 110,
  "flags_solved": 1, "flags_total": 2,
  "created_at": "...", "ready_at": "...", "error": null
}
```

## Chat

| Method | Path | Notes |
|---|---|---|
| POST | `/sessions/{id}/chat` | `{content}` — user message; `/` prefixes are intercepted as slash commands (`/autonomy`, `/subagents`) |
| GET | `/sessions/{id}/chat` | Recent messages (roles: user/coach/system; kinds: chat, hint, nudge, suggestion, action_report) |

## Engine & admin

| Method | Path | Notes |
|---|---|---|
| GET | `/engine/status` | Provider health `{mode, reachable}` |
| GET | `/engine/metrics?timeframe=hour|day|week|month` | PVE RRD time series (mock → unavailable) |
| GET | `/engine/resources` | Capacity vs `resources.max_*` budget |
| GET | `/engine/disks` | Disk usage |
| GET | `/engine/storage` | Storage pools |
| GET | `/engine/hoststats` | CPU temps/GPU/fans via `engine.hoststats_url` |
| GET | `/admin/kali-template/templates` | Available Ludus templates |
| GET | `/admin/kali-template/status` | Builder state (`idle`, `kali.builder_vmid`) |
| POST | `/admin/kali-template/build` | `{base_template}` → clone builder VM on WAN bridge |
| POST | `/admin/kali-template/finalize` | Convert builder → template, set `engine.kali_template` |
| POST | `/admin/kali-template/abandon` | Delete the in-flight builder VM |
| GET | `/admin/console/vm/{vmid}/ticket` | Admin console ticket for a standalone VM |

## LLM helpers

| Method | Path | Notes |
|---|---|---|
| POST | `/llm/models` | `{base_url?, api_key?}` → proxied `{base_url}/models` list |
| POST | `/llm/test` | Probe the endpoint end-to-end (incl. vision capability) |
| POST | `/llm/reasoning-efforts` | Parse supported `reasoning_effort` values |
| GET | `/llm/usage?days=N` | Tokens/requests/latency per day + budget fill |

## Stats & profile

| Method | Path | Notes |
|---|---|---|
| GET | `/profile` | XP, solve counts |
| PATCH | `/profile` | Profile fields |
| GET | `/stats/activity` | Activity feed/aggregates for `/stats` |

## Telemetry ingest

| Method | Path | Notes |
|---|---|---|
| POST | `/telemetry` | `{session_id, events[]}` — per-session telemetry token, **not** the admin bearer |

## Coach-internal API (service token)

`/api/coach/*` — gated by `Authorization: Bearer $PENTRAIN_COACH_SERVICE_TOKEN`
(unset → warn-and-open, set a real one in production).

| Method | Path | Purpose |
|---|---|---|
| GET | `/coach/active-sessions` | ready/active sessions — post-restart attach sweep |
| GET | `/coach/session/{id}/context` | Full coach context: quest, briefing, checkpoints, telemetry digest |
| GET | `/coach/config` | LLM + coach runtime settings |
| GET | `/coach/messages/{id}` | Last 50 chat messages |
| POST | `/coach/message` | `{session_id, kind, content, meta}` → persisted coach message |
| POST | `/coach/stream` | `{session_id, draft_id, content, reasoning, done, kind}` — ephemeral draft relay (sticky until `done`) |
| POST | `/coach/activity` | `{session_id, active, text}` — "coach is doing X" indicator |
| POST | `/coach/suggest` | `{session_id, command, why}` → suggestion chip |
| POST | `/coach/exec` | `{session_id, command, window?}` → run in Kali tmux pane |
| POST | `/coach/type` | `{session_id, text, window?}` → type into busy pane |
| POST | `/coach/flag` | `{session_id, value}` → submit flag |
| POST | `/coach/flag-check` | `{session_id, flag_key}` |
| POST | `/coach/checkpoint` | `{session_id, checkpoint_id}` |
| POST | `/coach/screen` | `{session_id}` → Kali screenshot (vision) |
| POST | `/coach/llm-usage` | `{…usage row…}` — fire-and-forget stats |
| POST | `/coach/profile` | Session profile mirror |

## WebSockets

| Path | Consumer | Events |
|---|---|---|
| `/ws/session/{id}` | Session page | `state`, `deploy_log`, `coach_message`, `coach_stream`, `coach_activity`, `flag`, `hint`, `telemetry`, `autonomy`, `subagents`, `internet` |
| `/ws/coach` | Coach service | All session events + chat + telemetry — the event feed the policy gate consumes |
| `/api/console/{id}` | Session console | Bidirectional VNC frames (proxied noVNC) |
| `/api/console/vm/{vmid}` | Admin console | Same pipe for a standalone VM (template builder) |

Coach WS payload `PENTRAIN_COACH_SERVICE_TOKEN` bearer; session console WS
authenticates via the `ticket` query param minted by `GET …/console`.
