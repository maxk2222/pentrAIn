# Ops runbook

Day-2 operations for the pentrain-app stack (backend, coach, frontend, SQLite).

## CLI

`cli/pentrain` — thin wrapper, run from the repo checkout on the app host:

```
pentrain doctor          # environment diagnostic — start here
pentrain up|down|logs    # docker compose lifecycle (engine/docker-compose.yml)
pentrain sync-packs      # re-import content/packs into the DB
pentrain engine-status   # provider health + resource caps
pentrain pack-lint       # scripts/lint_packs.py
```

## Logs

```
docker compose -f engine/docker-compose.yml logs -f backend
docker compose -f engine/docker-compose.yml logs -f coach
```

Useful signals: `coach attached`, `deploy finished`, `packs synced`,
`llm call failed`, `event stream dropped, reconnecting`.

## Common problems

**Coach is silent.**
Check in order:
1. `coach.enabled` in Settings, plus the session's coach toggle.
2. `llm.base_url` / `llm.api_key` / `llm.model` — `llm call failed` in the
   coach log means the endpoint is unreachable or rejected the request.
3. Daily token budget (`llm.daily_token_budget`) — the coach announces once
   in chat, then pauses.
4. By design the coach does not comment on commands — it speaks on chat
   messages, flags, checkpoints, and when the policy detects stuck/idle.
   Silence during normal work is intended behavior.

**Deploy hangs / fails.**
Deploy logs stream into the session's Log tab. On a real engine check the
Ludus API (`ludus` service + templates present, `ludus templates list`) —
PenTrAIn only orchestrates it. Mock mode always completes.

**Console black / disconnected.**
The console proxies Proxmox noVNC for the session's Kali VMID. If it dies
after a reset, it reconnects automatically (new `ready_at` remounts the
view); the ⟳ button forces a new ticket. Persistent failure → engine creds
or the VMID changed under you (hard reset allocates a fresh range).

**No telemetry / checkpoints dead.**
`pentrain-telemetried.service` on the Kali VM must be running
(`systemctl status pentrain-telemetried`). The shell hook (`hook.sh`) logs
commands; the daemon ships them to `/api/telemetry` with the session token.

**Coach replies arrive whole, not streamed.**
`PENTRAIN_LLM_STREAM=false` or the LLM endpoint lacks SSE — the code falls
back automatically; only perceived latency changes.

## Resets

- **Soft reset** — Ludus snapshot rollback; fast; flags re-randomize
  (`ExpectedFlag` rows are replaced, old values stop working).
- **Hard reset** — range destroyed and redeployed; new VMIDs, new networks.

## Backup

All platform state is `pentrain-data` volume → `/data/pentrain.db` (SQLite).
Stop the stack, copy the file. User progress, scores, settings and chat
history live there; ranges are disposable by design.

## Upgrading content

Edit packs → `pentrain pack-lint` → `pentrain sync-packs` (or the Settings
"Sync packs" button). Changed `quest.yaml` applies to *new* sessions only —
running sessions keep their deploy-time snapshot of the definition.
