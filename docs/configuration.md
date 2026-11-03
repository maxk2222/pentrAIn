# Configuration

pentrAIn keeps **all runtime configuration in the database** (`settings`
table), editable live via the WebGUI (**Settings** page) or
`PATCH /api/settings`. Env vars only control process-level bootstrap
(location of the DB, engine bootstrap credentials, service tokens, ports).

> [!NOTE]
> Settings marked **secret** are redacted to `********` in `GET /settings`
> and never rendered into coach/LLM context. Patching `********` back keeps
> the stored value. Non-registered keys pass through `PATCH` (typed coercion
> only applies to the registry).

## Settings registry

### Engine

| Key | Default | Meaning |
|---|---|---|
| `engine.mode` | `nested` | `nested` \| `direct` \| `mock` |
| `engine.pve_url` | — | Proxmox API URL, e.g. `https://engine:8006` |
| `engine.pve_node` | `pve` | PVE node name |
| `engine.pve_token_id` | — | `user@realm!tokenid` |
| `engine.pve_token_secret` | — | 🔒 PVE token secret |
| `engine.ludus_url` | — | Ludus API URL, e.g. `https://engine:8081` |
| `engine.ludus_api_key` | — | 🔒 Ludus API key |
| `engine.hoststats_url` | — | pentrain-hoststats agent; empty → derived from `pve_url` port `9100` |
| `engine.testing_mode` | `true` | Cut range internet after deploy (Ludus testing mode) |
| `engine.testing_allow` | `[]` | CIDRs still reachable in testing mode (the app VM itself) |
| `engine.kali_template` | — | Custom Kali template name — empty = per-quest default; set by the builder |
| `engine.kali_wan_bridge` | `vmbr0` | Bridge with real LAN/internet — Kali `net1` + builder VM |
| `kali.internet_default` | `false` | Attach the WAN NIC to every new session |
| `kali.builder_vmid` | `0` | Internal: in-flight template-builder VM |
| `lan.scope_cidr` | — | Authorized LAN scope for home-lab quests; empty → auto-detect /24 from WAN lease |
| `platform.api_url` | `http://pentrain-app:8000` | Backend URL reachable **from inside ranges** (telemetry ingest) |

### Resource budget

Quests that exceed the budget stay locked in the library (`check_unlock`).

| Key | Default |
|---|---|
| `resources.gate_mode` | `live` |
| `resources.ram_headroom` | `0.85` |
| `resources.vcpu_overcommit` | `4.0` |
| `resources.max_ram_gb` | `48` |
| `resources.max_vcpus` | `16` |
| `resources.max_disk_gb` | `500` |

`gate_mode`: `live` weighs each quest's ballooning floor against free host
RAM × `ram_headroom`, host cores × `vcpu_overcommit`, disk, and template
presence (falls back to `static` budgets when PVE is unreachable);
`static` = the `max_*` budgets only; `off` = no capacity gate.

### LLM

| Key | Default | Meaning |
|---|---|---|
| `llm.base_url` | `http://localhost:11434/v1` | OpenAI-compatible endpoint |
| `llm.api_key` | — | 🔒 Bearer for the endpoint |
| `llm.model` | `huihui-ai/Qwen3-30B-A3B-abliterated` | Chat/tool-calling model |
| `llm.vision_model` | — | Enables `capture_screen` |
| `llm.temperature` | `0.4` | |
| `llm.daily_token_budget` | `10000000` | 0 = unlimited |
| `llm.reasoning` | `true` | Let thinking models reason before answering |
| `llm.reasoning_effort` | `medium` | `low`/`medium`/`high` — values probed per endpoint |

### Coach

Full semantics in [coach.md](coach.md#coach-tuning).

| Key | Default | Meaning |
|---|---|---|
| `coach.enabled` | `true` | Master switch |
| `coach.default_autonomy` | `2` | Level for new sessions (1–4) |
| `coach.verbosity` | `normal` | `terse`/`normal`/`verbose` |
| `coach.personality` | `mentor` | Persona |
| `coach.reflect_interval_s` | `60` | Wall-clock reflection tick |
| `coach.nudge_after_s` | `480` | Idle → nudge threshold |
| `coach.hint_after_s` | `900` | Idle → hint threshold |
| `coach.action_budget` | `400` | Max coach executions/session (parent) |
| `coach.action_grace` | `80` | Soft-cap window after the budget |
| `coach.takeover_pace_s` | `10` | Min gap between L4 chains |
| `coach.takeover_chain_max` | `48` | Max LLM calls per L4 turn |
| `coach.max_workers` | `8` | Parallel subagent panes (`w1`–`w8`) |
| `coach.worker_turn_cap` | `80` | LLM turns per worker |
| `coach.worker_time_cap_s` | `3600` | Wall-clock per worker |
| `coach.collect_wait_s` | `240` | `collect_agent` block bound |
| `coach.wait_max_s` | `600` | Cap per `wait` tool call |
| `coach.observer_enabled` | `true` | Session observer: tips + field notes |
| `coach.observer_tick_s` | `60` | Trajectory poll interval |
| `coach.observer_stuck_s` | `600` | No-progress window = stuck |
| `coach.observer_min_denials` | `2` | Denial floor for stuck detection |
| `coach.observer_max_proposals` | `2` | Lessons per analysis call |
| `coach.observer_max_lessons_session` | `4` | Lesson cap per session |
| `coach.observer_cooldown_s` | `900` | Min gap between analyses |
| `coach.observer_hint_min_level` | `3` | Live tips need autonomy ≥ this |

### Content & data

| Key | Default | Meaning |
|---|---|---|
| `content.packs` | `["bundled"]` | Pack sources |
| `data.telemetry_retention_days` | `30` | Telemetry retention |
| `security.admin_token_hash` | — | 🔒 scrypt admin hash (set via wizard/login) |
| `setup.completed` | `false` | Wizard gate |

## Environment variables

### Backend (`backend/app/config.py`, prefix `PENTRAIN_`)

| Var | Default | Meaning |
|---|---|---|
| `PENTRAIN_DATABASE_URL` | `sqlite+aiosqlite:///./pentrain.db` | SQLAlchemy URL — `/data/pentrain.db` in docker |
| `PENTRAIN_CONTENT_DIR` | `/content/packs` | Where packs are mounted |
| `PENTRAIN_ENGINE_MODE` | `nested` | Bootstrap engine mode (settings override per request) |
| `PENTRAIN_PVE_URL` / `_TOKEN_ID` / `_TOKEN_SECRET` / `_NODE` / `_VERIFY_TLS` | — | Bootstrap PVE credentials |
| `PENTRAIN_LUDUS_URL` / `_API_KEY` | — | Bootstrap Ludus credentials |
| `PENTRAIN_COACH_SERVICE_TOKEN` | `dev-coach-token` | Shared secret backend↔coach — **set a real value** (default prints a startup warning) |
| `PENTRAIN_APP_SECRET` | `dev-secret-change-me` | Signs flag HMAC + session tokens — generated at install |
| `PENTRAIN_CORS_ORIGINS` | `*` | Tightened at install |
| `PENTRAIN_LOG_LEVEL` | `INFO` | |

### Coach (`coach/coach/config.py`, prefix `PENTRAIN_`)

| Var | Default | Meaning |
|---|---|---|
| `PENTRAIN_BACKEND_URL` | `http://backend:8000` | REST base |
| `PENTRAIN_BACKEND_WS_URL` | `ws://backend:8000/ws/coach` | Event feed |
| `PENTRAIN_COACH_SERVICE_TOKEN` | `dev-coach-token` | Must match the backend's |
| `PENTRAIN_LLM_TIMEOUT_S` | `600` | Per-request LLM timeout |
| `PENTRAIN_LLM_STREAM` | `true` | SSE draft streaming (auto-fallback) |
| `PENTRAIN_LLM_*` | — | `PENTRAIN_LOG_LEVEL` as above |

> [!WARNING]
> `PENTRAIN_APP_SECRET` change rotates **all** flag derivations — running
> sessions' flags would stop validating. The installer generates it once;
> treat it like a database-level secret (back it up with `pentrain.db`).

## Where things live

| Artifact | Location |
|---|---|
| Runtime config | `settings` table in `pentrain.db` (docker volume `pentrain-data` → `/data`) |
| Installer-generated secrets | `installer/.secrets/` — gitignored, never commit |
| Ansible config | `installer/inventory.yml` + `installer/group_vars/all.yml` |
| Docker env | `engine/docker-compose.yml` service `environment:` blocks |
