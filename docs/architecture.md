# Architecture

pentrAIn is three processes plus a range engine, glued by REST and
WebSockets. State lives in one SQLite file; the hypervisor is someone else's
problem (Ludus on Proxmox).

## Component map

```mermaid
flowchart TB
    subgraph Browser["Browser"]
        FE["React 19 SPA<br/>Vite · Tailwind · noVNC"]
    end

    subgraph App["pentrain-app (docker compose)"]
        BE["backend · FastAPI<br/>quests · sessions · flags · WS hub · console proxy"]
        CO["coach · agent service<br/>policy · LLM turns · workers"]
        DB[("SQLite<br/>pentrain.db")]
    end

    subgraph Engine["Engine host (Proxmox VE + Ludus)"]
        PVE["PVE REST :8006<br/>VM lifecycle · QGA · vncwebsocket"]
        LUD["Ludus API :8081<br/>ranges · templates · testing mode"]
        subgraph Range["per-session range (isolated /24)"]
            RT[router VM]
            K["Kali VM<br/>telemetried + QGA"]
            T1[target VM]
            T2[target VM]
        end
    end

    FE -- "REST /api/* · WS /ws/* · WS /api/console/*" --> BE
    CO -- "REST /api/coach/* (service token)<br/>WS /ws/coach (events)" --> BE
    BE --> DB
    BE -- "range build/status" --> LUD
    BE -- "QGA file-write/exec · VNC ticket · metrics" --> PVE
    K -- "command telemetry (per-session token)" --> BE
    BE -. "console proxy" .-> PVE
    FE -. "noVNC frames (proxied)" .-> BE
    CO -. "LLM /v1/chat/completions" .-> LLM["OpenAI-compatible LLM<br/>(self-hosted recommended)"]
```

| Piece | Role |
|---|---|
| `backend/` | FastAPI app factory (`app.main:create_app`); API under `/api`, WS under `/ws` + `/api/console`; SQLAlchemy async + SQLite; in-process event bus per session |
| `coach/` | Standalone asyncio service; attaches to ready/active sessions over `/ws/coach`; reacts to session events with policy-gated LLM turns |
| `frontend/` | React 19 SPA — TanStack Query for REST, raw WS for live events, noVNC for consoles |
| `content/` | Quest packs (`content/packs/<track>/<quest>/`) + `pentrain_*` Ansible roles applied by Ludus at deploy |
| `telemetry-agent/` | `pentrain-telemetried` — bash hook + daemon inside Kali, ships the command stream to `/api/telemetry` with a per-session token |
| `installer/` | Ansible bootstrap — nested engine VM or direct host; see [getting-started](getting-started.md#two-install-modes) |
| `cli/pentrain` | Operator CLI: `doctor`, `up/down/logs`, `pack-lint`, `sync-packs`, `new-quest`, `install` |

## The engine abstraction

```mermaid
classDiagram
    class RangeProvider {
        <<abstract>>
        +deploy(session, spec)
        +reset(session, hard)
        +destroy(session)
        +status()
        +console_ticket(...)
        +agent_exec / agent_file_write
        +metrics(...)
        +apply_kali_internet(...)
        +kali_template_*(...)
    }
    class PveLudusProvider {
        Ludus REST → ranges
        PVE REST → VMs, QGA, noVNC, RRD
    }
    class MockProvider {
        simulated lifecycle
        canned console/metrics
    }
    RangeProvider <|-- PveLudusProvider
    RangeProvider <|-- MockProvider
```

`backend/app/services/engine.py` picks the provider once at startup:
`engine.mode` `nested`/`direct` → `PveLudusProvider` (needs PVE + Ludus
credentials), `mock` or missing credentials → `MockProvider`. Everything
upstream (sessions, flags, console, metrics) talks to the abstraction, so
dev mode exercises the same code path.

## Session lifecycle

```mermaid
stateDiagram-v2
    [*] --> queued: POST /api/sessions
    queued --> deploying: provider.deploy()
    deploying --> ready: deploy done + flags injected
    deploying --> failed: error (recovery retries on startup)
    ready --> active: POST /activate
    active --> solved: last flag accepted
    active --> resetting: POST /reset {hard:false|true}
    resetting --> ready
    active --> aborted: POST /abort
    ready --> aborted: POST /abort
    solved --> [*]
    aborted --> [*]
    failed --> [*]
```

Notes:

- **`ready` vs `active`** — a deployed range waits for you to click *Start
  hacking*; activation is what starts the scoring clock and opens the coach.
- **Soft reset** = snapshot rollback on every range VM, then fresh flag
  secrets are injected. **Hard reset** = destroy + full redeploy.
- **Startup recovery** — on boot the backend sweeps sessions stuck in
  `deploying`/`resetting` and resumes or fails them cleanly, so a restart
  never orphans a range.
- Sessions persist in SQLite; ranges are disposable — progress is score, not
  VM state.

## Deploy + flag injection sequence

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant BE as Backend
    participant LU as Ludus
    participant PVE as Proxmox
    participant VM as Target VM
    FE->>BE: POST /api/sessions {quest_id}
    BE->>LU: create range (topology → VMs, VLANs, router)
    LU->>PVE: clone templates → range VMs
    loop poll
        BE->>LU: range status → SUCCESS + vmids
    end
    BE->>PVE: wait QGA ping on every VM
    BE->>PVE: snapshot all VMs (post-deploy state)
    loop each flag (kind: file)
        BE->>PVE: QGA file-write → file_path = pentrAIn{hmac}
    end
    BE->>BE: publish state=ready (WS)
    BE-->>FE: session ready
```

- Flag secrets are `pentrAIn{<hex>}` derived by **HMAC over the session's
  `flag_seed`** — generated per session, rotated on soft reset.
- `kind: command` flags need no injection — the backend runs a check command
  on the target (POSIX shell; Linux only) and compares output.
- Long guest commands are written via the **QGA file API** and executed as a
  short `timeout 55 sh /tmp/...` — dumping multi-line scripts into
  `agent/exec` wedges the virtio channel.

## Coach event flow

```mermaid
flowchart LR
    subgraph Sources["Event sources"]
        TEL["telemetry<br/>(command stream)"]
        CHAT["user chat"]
        FLAG["flag submit"]
        TICK["wall-clock reflect tick"]
    end
    Sources --> EV["session event bus<br/>+ /ws/coach"]
    EV --> POL{"policy gate<br/>silence default, backoff,<br/>budgets, checkpoints"}
    POL -->|act| LLM["LLM turn<br/>tools_for_level()"]
    POL -->|drop| QUIET["state updated,<br/>no reply"]
    LLM --> ACT["tool calls<br/>→ /api/coach/*"]
    ACT --> UI["session WS<br/>→ chat/stream/action cards"]
    ACT --> KALI["exec/type in<br/>pentrain-coach tmux"]
```

- The coach attaches to every `ready`/`active` session after a restart sweep
  (`GET /api/coach/active-sessions`).
- Per session it keeps a compact context: quest briefing
  (`coach_context.md`), checkpoints, telemetry digest, recent chat.
- Per-LLM-call the tool schema is rebuilt from `level` + `subagents` — the
  model cannot select an action the gate would refuse.
- L4 chains loop `tool_call → result → next call` bounded by
  `coach.takeover_chain_max` with `coach.takeover_pace_s` between chains.

## Console proxy

```mermaid
sequenceDiagram
    participant FE as Browser (noVNC)
    participant BE as Backend
    participant PVE as Engine PVE
    FE->>BE: GET /api/sessions/{id}/console → ticket
    BE->>PVE: vncproxy POST (vmid) → ticket + port
    BE-->>FE: {ticket, port, vmid}
    FE->>BE: WS /api/console/{id}?ticket=…
    BE->>PVE: WSS vncwebsocket?ticket=…
    PVE-->>BE: VNC frames (binary)
    BE-->>FE: VNC frames (binary)
    Note over FE,PVE: bidirectional pipe — reconnects mint fresh tickets
```

The admin console for the Kali template builder uses the same pipe with an
explicit VMID (`/api/console/vm/{vmid}` + `/api/admin/console/vm/{vmid}/ticket`).

## Browser terminals

Terminal tabs are a **second interactive path into Kali** — the Kali VM is
inbound-isolated, so the connection is *reversed*: the browser opens a user
WS, which registers a channel "want"; `telemetried` polls the want list and
dials an outbound data WS; the backend pipes the two sockets.

```mermaid
sequenceDiagram
    participant FE as Browser (xterm)
    participant BE as Backend terminal hub
    participant AG as telemetried (kali)
    FE->>BE: WS /api/terminal/{id}/{chan}?cols&rows → want registered
    AG->>BE: GET /api/terminal/wants/{id} (poll ~2s)
    BE-->>AG: {chan: {cols, rows}}
    AG->>BE: WS /api/terminal/kali/{id}/{chan} → paired
    BE-->>FE: status live — PTY bytes flow both ways
    Note over AG: tmux new-session -A -s pentrain-web-<chan><br/>survives reconnects + page reloads
```

- Resize rides in-band as a JSON control frame (`{"t":"resize",…}` →
  `TIOCSWINSZ`); all other text frames are status (`live`/`exit`/`error`).
- `want` entries persist until the session leaves `ready`/`active` or the
  want is idle >5 min, so an agent reconnect re-dials and reattaches the
  same tmux instead of restarting the shell.
- Shell access is gated by `SHELL=1` in the kali-only telemetried config —
  target VMs run the same daemon but never get the flag, so no browser shell
  lands on a flag-bearing target.

## Telemetry

The Kali template ships `pentrain-telemetried`: a bash `DEBUG`-trap hook
(`hook.sh`) appends commands; the daemon batches them to
`POST /api/telemetry` with a per-session token minted at deploy. Telemetry
drives checkpoints, the activity feed and the coach's context — and is
explicitly treated as untrusted text in the prompt.

## Data model (SQLite, core tables)

```mermaid
erDiagram
    TRACK ||--o{ QUEST : contains
    QUEST ||--o{ FLAG : defines
    QUEST ||--o{ SESSION : played_in
    SESSION ||--o{ EXPECTED_FLAG : holds
    SESSION ||--o{ FLAG_SUBMISSION : receives
    SESSION ||--o{ COACH_MESSAGE : has
    SESSION ||--o{ COACH_ACTION : records
    SESSION ||--o{ TELEMETRY_EVENT : streams
    SESSION ||--o{ HINT_USE : spends
    SESSION ||--o{ QUEST_CHECKPOINT : passes
    SESSION ||--o{ ASSIST_USE : records_aid
    SESSION ||--o{ ATTEMPT : scores
    USER_PROFILE ||--|| SESSION : xp_from
    LLM_USAGE }o--|| COACH : posted_by
    SETTING ||--|| BACKEND : configures
    COACH_SESSION_STATE ||--|| SESSION : mirrors
```

| Table | Contents |
|---|---|
| `tracks` / `quests` / `flags` | Pack-synced catalog (source of truth = files in `content/packs`) |
| `sessions` | Lifecycle state, `flag_seed`, `autonomy_level`, `subagents_enabled`, vmids, error |
| `expected_flags` | HMAC-derived secrets for this session (rotated on soft reset) |
| `flag_submissions` | Every attempt, correct or not |
| `attempts` | Leaderboard rows: score, time, solve style |
| `assist_uses` | Which aids (sheet/coach/hints/takeover) a solve used |
| `coach_messages` / `coach_actions` | Chat history + executed tool calls |
| `coach_session_state` | Coach memory per session (policy state) |
| `telemetry_events` | Command stream (retention: `data.telemetry_retention_days`, 30 d) |
| `quest_checkpoints` | Coach-detected progress markers |
| `llm_usage` | Fire-and-forget rows: tokens/latency per call |
| `user_profile` | XP aggregate |
| `settings` | The whole runtime config — see [configuration.md](configuration.md) |

## Security boundaries in one picture

```mermaid
flowchart LR
    subgraph LAN["Your LAN"]
        USER[trainee browser] --> APP[pentrain-app]
        APP -->|LAN only — never expose| WARN["no port-forward;<br/>VPN/rev-proxy for remote"]
    end
    subgraph Range["isolated range /24"]
        KALI --> T[target VMs]
    end
    KALI -. "net1 uplink (opt-in)" .-> LAN
    T -.->|no route| LAN
```

Details and the full threat model: [SECURITY.md](SECURITY.md).
