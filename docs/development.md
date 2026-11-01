# Development

The whole platform — UI, session lifecycle, coach plumbing, flags — runs
against **MockProvider** on a laptop. No Proxmox, no Ludus, no VMs.

## Prereqs

| Tool | Version |
|---|---|
| Python | 3.11+ (3.13 works — `passlib` patch included) |
| Node | 20+ |
| Docker | only for the containerized stack (optional) |

```bash
# one-time: create the venvs
python3 -m venv backend/.venv  && backend/.venv/bin/pip  install -r backend/requirements.txt
python3 -m venv coach/.venv    && coach/.venv/bin/pip    install -r coach/requirements.txt
cd frontend && npm install
```

## The dev loop

```bash
make dev
# backend :8000 (uvicorn --reload, mock engine)
# coach   (attaches over ws://localhost:8000/ws/coach)
# frontend:5173 (vite, proxies /api + /ws → :8000)
```

Or individually: `make backend-dev` / `make coach-dev` / `make frontend-dev`.

> [!TIP]
> The bundled `.env` handling (`pydantic-settings`, `env_file=".env"`) reads
> repo-root `.env` automatically — put `PENTRAIN_*` overrides there, never in
> tracked config.

## Project layout

```
backend/   FastAPI app factory (app.main:create_app)
  app/api/        route modules — sessions, library, streams, admin
  app/services/   sessions, flags, engine, packs, settings, kali_net,
                  kalibuild, console, coach_bridge, telemetry, stats
  app/models/     domain.py (SQLAlchemy), schemas.py (pydantic)
coach/     standalone agent service
  coach/loop.py   session attach + event loop + dispatch + workers
  coach/policy.py silence/escalation/backoff rules
  coach/tools.py  native tool-calling contract (single source of truth)
  coach/state.py  per-session working state
  coach/prompts*  system/worker prompt builders
frontend/  React 19 + Vite 6 + TS + Tailwind v4 + TanStack Query
  src/pages/      Dashboard, Library, QuestDetail, Session, Leaderboard,
                  Stats, Settings, Setup, Login
  src/components/ console (noVNC), chat, objectives, sheet, notes, livestats…
content/
  packs/          <track>/<quest>/ — quest.yaml + briefing/defense/cheatsheet
  ansible-roles/  pentrain_* roles applied by Ludus at deploy
engine/    docker-compose.yml — app stack on the engine/app VM
installer/ Ansible nested|direct bootstrap
telemetry-agent/ telemetried.py + hook.sh + systemd unit
cli/pentrain      operator CLI (doctor, up/down/logs, pack-lint, sync-packs…)
scripts/   lint_packs.py, new_quest.py, wifi/PCAP generators
docs/      this documentation + media/ capture pipeline
```

## Tests & checks

| Command | What |
|---|---|
| `make test` | Backend + coach pytest suites (≈280 tests) |
| `make test-backend` | `backend/.venv/bin/python -m pytest -q` |
| `make test-coach` | `coach/.venv/bin/python -m pytest -q` |
| `make lint-packs` | `scripts/lint_packs.py content/packs` — schema + role checks |
| `cd frontend && npm run lint` | ESLint |
| `cd frontend && npm run build` | Vite build (typecheck included) |
| `cd backend && ruff check` | Python lint (also covers coach) |

### Mock engine specifics

- `deploy`/`reset`/`destroy` complete instantly; console endpoint returns a
  placeholder (the page shows "Mock engine — no real Kali console").
- Flag secrets exist as `expected_flags` rows — check them in sqlite to
  exercise the submit path end-to-end.
- LLM calls are *not* mocked — coach turns still need an endpoint. For pure
  UI work, chat/coach panels accept injected messages via the
  coach-internal API (the docs [media pipeline](media/README.md) uses this).

## Docker stack

```bash
docker compose -f engine/docker-compose.yml up --build
# backend :8000 · frontend :80 · coach — pentrain-data volume → /data/pentrain.db
```

> [!NOTE]
> Older docs referenced `docker-compose.dev.yml` — that file no longer
> exists. Local development = `make dev` (bare metal + mock engine).

## CLI

`cli/pentrain` — run from a checkout on the app host (or any machine with the
compose file):

```text
doctor         full environment diagnostic — start here
up|down|logs   docker compose lifecycle
build          rebuild images
engine-status  provider health/mode via backend
pack-lint      validate quest packs
new-quest      scaffold a quest (+ --role for the role skeleton)
sync-packs     reload packs into a running backend
install        run the Ansible installer
```

`engine-status` and `sync-packs` need `PENTRAIN_TOKEN` once an admin password
is set.

## Contributing a quest

1. `python scripts/new_quest.py <track> <quest-id> --tier N --role`
2. Write `quest.yaml` + markdown artifacts → [quest-authoring.md](quest-authoring.md)
3. `make lint-packs` → `pentrain sync-packs` → deploy in mock or real mode

## Useful places to start reading

| To understand… | Read |
|---|---|
| Session lifecycle | `backend/app/services/sessions.py` |
| Flag derivation + injection | `backend/app/services/flags.py` |
| Engine abstraction | `backend/app/ranges/base.py`, `services/engine.py` |
| Kali uplink mechanics | `backend/app/services/kali_net.py` |
| Coach decision loop | `coach/coach/loop.py`, `policy.py` |
| Tool contract | `coach/coach/tools.py` |
| Session UI | `frontend/src/pages/Session.tsx` |
| API client | `frontend/src/lib/api.ts` |
