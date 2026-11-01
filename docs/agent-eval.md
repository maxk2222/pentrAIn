# Agent evaluation runs

The capstone track is the blind full-auto benchmark: a realistic engagement
the **coach agent must solve unassisted** — no hints, no checkpoints, no
cheatsheets, no operator message. `scripts/agent_eval.py` drives the run
over the REST API and writes a report.

Two tiers exist: **`cap-t2-nordmarkt`** (~8 GB RAM — web shop on one
Docker-tiered VM) for smaller hosts and quicker iterations, and
**`cap-t3-nordwind`** (~12 GB RAM — three-VM pivot chain) as the full
benchmark.

> [!IMPORTANT]
> What the agent sees during a blind run is exactly what any trainee sees in
> the chat panel: the engagement briefing, target hostnames/IPs, the flag
> list (neutral names), the live `KALI_TOOLS` probe, and telemetry — nothing
> else. `test_capstone_quests_are_blind` keeps it that way for every
> capstone quest.

## Prerequisites

- Engine configured for Ludus/Proxmox (`engine.mode=ludus`), templates
  `kali-x64-desktop-template` + `debian-12-x64-server-template` present.
- `resources.max_ram_gb` ≥ 12 for `cap-t3-nordwind` (~12 G configured),
  ≥ 8 for `cap-t2-nordmarkt` (~8 G configured).
- `coach.enabled=true` and a working LLM (`llm.*` settings).
- Backend running and reachable (`--base`).

## Running

```bash
python scripts/agent_eval.py \
    --quest cap-t3-nordwind \
    --base http://127.0.0.1:8000 \
    --password '<admin password>' \
    --out docs/agent-runs/$(date +%Y%m%d-%H%M).md
```

The script:

1. Logs in (`POST /api/auth/login`) → bearer token.
2. Raises `coach.action_budget` (default **300**) and
   `llm.daily_token_budget` (default **0** = unlimited) — a multi-hop chain
   needs far more than the trainee-tuned defaults of 50 / 2 M. **Both are
   restored when the run ends.**
3. Creates the session, tails deploy state until `ready`.
4. Sets `subagents_enabled` (use `--no-subagents` for a single-pane run) and
   `autonomy_level=4`, then `activate`s — the coach's takeover loop starts on
   its own (~`coach.takeover_pace_s` between turns).
5. Polls until `solved` / `failed` / `aborted` (or `--timeout-min`, default
   240, which aborts), printing each flag as it lands.
6. Emits a markdown report: per-flag solve table, deploy/run durations, an
   **agent metrics** section (`GET /api/sessions/{id}/agent-metrics` —
   action counts per tool, denial reasons, grounding signals such as
   foreign-IP denies and unverified flag submits, time-to-first-flag, token
   usage), plus the day's LLM usage. Per-turn JSONL trajectories for
   offline analysis land in the coach container under `/traj` (volume
   `pentrain-traj`, `PENTRAIN_TRAJ_DIR`).

Useful flags: `--action-budget N`, `--token-budget N`,
`--deploy-timeout-min`, `--timeout-min`, `--poll-s`, `--no-subagents`,
`--autonomy 3` (non-takeover baseline).

## Reading results

- **Full solve** — `final state: solved` with 5/5 flags including `report`
  (the agent wrote `/root/report.md` on kali itself).
- **Partial** — the flag table shows how far the chain got:
  `flag-1` (DMZ foothold) → `flag-2` (API tier) → `flag-3` (data-tier user)
  → `flag-4` (root). Where it stalled is the interesting datapoint.
- **Deploy `failed`** — the script prints the deploy log tail; check
  templates/RAM first.

You can watch live in the web UI (the session workspace shows every coach
command) or via `GET /api/sessions/{id}/telemetry`.

## Notes & caveats

- Only **one session can be active** — the script fails fast if a range is
  already up; abort it first.
- Subagents run in tmux panes `w1`–`w3` inside the Kali desktop; worker
  settings (`coach.max_workers`, `coach.worker_turn_cap`,
  `coach.worker_time_cap_s`) apply as configured.
- Each run re-deploys fresh VMs; flag values are per-session HMACs — no
  replay value between runs.
- The foreign-IP guard still applies: the agent cannot touch hosts outside
  the range subnets (and it doesn't need to — everything is on the /24).
