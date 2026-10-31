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

## Stats page (`/stats`)

Three panels:

- **Engine host** — CPU/RAM/network/load time series, proxied live from PVE
  `GET /nodes/{node}/rrddata` (`GET /api/engine/metrics?timeframe=hour|day|week|month`).
  Mock engine → panel degrades to "unavailable", nothing is stored locally.
- **Session VMs** — live per-VM gauges (cpu, ram, balloon target) via
  `GET /api/sessions/{id}/metrics` → `qemu/{vmid}/status/current`, 15s refresh.
- **Coach LLM usage** — the coach posts a fire-and-forget row per request to
  `POST /api/coach/llm-usage` (service token); `GET /api/llm/usage?days=N`
  aggregates tokens/requests/latency per day plus the daily-budget fill level.
  Rows live in the `llm_usage` table (~200B each, no retention job needed).

Reasoning effort: the Settings dropdown is probed from the endpoint
(`POST /api/llm/reasoning-efforts` sends an invalid effort and parses the
"Supported values: …" reply — LM Studio/Qwen report `none,minimal,low,
medium,high,xhigh`). Endpoints that ignore the field get the union fallback,
marked "· defaults" in the UI.

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
pentrAIn only orchestrates it. Mock mode always completes.

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

## Installer

- Full ansible output lands in `installer/logs/install.log` regardless of the
  live status board. Re-run `./install.sh --verbose` for raw task dumps.
- The installer is idempotent — re-running the same command resumes past
  already-done tasks.
- Non-interactive shells (CI, pipes) get plain output automatically; force it
  with `PENTRAIN_UI=plain` or `NO_COLOR=1`.

## Windows / Active Directory quests

The `ad-t*` quests need Windows templates that are **not** built by default:

- Re-run the installer with `--with-templates`, or trigger the Ludus template
  build manually — `win2022-server-x64-template` (and `win11-22h2-x64-template`
  for `ad-t2`+ workstations). First build takes hours and tens of GB.
- Deploy times are long: `est_deploy_min` on AD quests is honest (25–60 min).
- Flag injection needs the **qemu guest agent** inside the Windows template —
  stock Ludus Windows templates ship it. A failed inject shows up as
  `flag <id> inject FAILED` in the session deploy log.
- Windows quests only use `kind: file` flags (`C:\flags\*.txt`) — `kind:
  command` checks run a POSIX shell and are rejected by the pack linter.
- AD t3 (`ad-t3-kill-chain`) wants ~48G RAM — check the admin resource budget
  or `check_unlock` keeps it locked.

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

## Rolling out new quests

New quests ship two artifacts that must land in different places:

1. **Packs** — `content/packs/` is mounted read-only into the backend
   container. Update the checkout, run `pentrain pack-lint`, then
   `pentrain sync-packs`. New quests appear in the library immediately;
   progression/exam gates are enforced at session start.
2. **Roles** — `content/ansible-roles/` live on the **PVE host**, not the
   app VM. Ludus only knows roles that were registered with it:

   ```bash
   # on the PVE host (e.g. ssh root@192.168.3.95)
   rsync -a content/ansible-roles/pentrain_<name>/ /opt/pentrain/ansible-roles/pentrain_<name>/
   for r in /opt/pentrain/ansible-roles/pentrain_*/; do
     ludus ansible role add -d "$r" -g
   done
   ludus ansible roles list | grep pentrain    # verify registration
   ```

   The installer does exactly this on each run — re-running the installer
   (or just this loop) is the supported resync path. Every role needs
   `tasks/main.yml` + `meta/main.yml` or Ludus refuses it; the pack linter
   fails early when a referenced role dir is missing.
3. Smoke-test one new quest end-to-end before announcing it (deploy →
   flag inject → submit → soft reset). Deploy logs land in the session's
   Log tab.

### Exam quests

`meta.exam: true` quests appear in the library with an **EXAM** badge and
unlock only after *all* teaching quests of that track+tier are solved.
Nothing extra to deploy — the gate is backend logic. AD exams
(`ad-t1-exam` … `ad-t3-exam`) reuse the teaching roles plus small
`pentrain_ad_tN_exam*` roles — same template requirements as the
corresponding tier (see "Windows / Active Directory quests" above).

## Wireless (hwsim) labs

The `wifi-*` quests simulate 802.11 **inside the target VM** using the
kernel's `mac80211_hwsim` module — no physical radios, no cross-VM
wireless (hwsim phys are kernel-local). Layout per quest:

- `pentrain_wifi_lab` (dependency of every wifi role) loads
  `mac80211_hwsim` at boot via `/etc/modules-load.d` + modprobe, installs
  `hostapd`/`aircrack-ng`/`hcxdumptool`/`hashcat`/`iw`, and drops lab
  users + wordlists under `/opt/wifi`.
- Quest roles spawn hostapd/wpa_supplicant pairs on the virtual phys —
  `wlan0`+ run the networks, `wlan1` is the trainee's attack interface.
- Trainees reach the lab by SSH from Kali (`wifi` user, creds in the
  briefing); attack tooling lives on the lab VM itself.
- Packaged captures (`files/*.cap`) are REAL hwsim-generated handshakes —
  regenerate with `scripts/make_wifi_handshake.sh <ssid> <psk> <out>`
  on a host that has hwsim + the wireless tools (PVE host works); validate
  with `aircrack-ng` before committing.
- Cleanup: ranges are destroyed whole, but if you run the generator on a
  shared host, kill leftover `hostapd`/`wpa_supplicant`/`airodump-ng` and
  `modprobe -r mac80211_hwsim` afterwards.
