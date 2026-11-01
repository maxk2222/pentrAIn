# Troubleshooting

Symptom → likely cause → fix. Start with `pentrain doctor` on the app host —
it checks docker, the backend, engine reachability, templates and disk in
one pass.

```bash
pentrain doctor                                   # the first responder
docker compose -f engine/docker-compose.yml logs -f backend
docker compose -f engine/docker-compose.yml logs -f coach
```

Useful log signals: `coach attached`, `deploy finished`, `packs synced`,
`llm call failed`, `event stream dropped, reconnecting`.

## Coach

### The coach never says anything

Walk this order:

1. **`coach.enabled`** in Settings **and** the session's coach state.
2. **LLM endpoint**: `llm.base_url`/`llm.api_key`/`llm.model` —
   `llm call failed` in the coach log means unreachable or rejected. Use
   Settings → *test* (`POST /api/llm/test`) to probe end-to-end.
3. **Daily budget**: `llm.daily_token_budget` exhausted — the coach
   announces once in chat, then pauses.
4. **By design**: the coach does not narrate commands. It speaks on chat
   messages, flag events, checkpoint escalations and stuck/idle policy.
   Silence during normal work is intended — see
   [coach.md](coach.md).

### Coach replies arrive whole, not streamed

`PENTRAIN_LLM_STREAM=false` or the endpoint lacks SSE — automatic fallback,
only perceived latency changes.

### Coach can't execute anything (L4)

- Autonomy is per-session: `/autonomy` (or the toolbar chips) — verify it
  actually says level 4.
- `coach.action_budget` (50) may be spent.
- Scope guard: commands targeting IPs outside the range (and
  `lan.scope_cidr`) are refused before reaching the VM.
- `suggest_command` chips are confirm-required — in L4 they aren't offered
  at all; look for action-report cards instead.

### Subagents never spawn

- Requires level **4** *and* the `Sub` toggle (`/subagents on`).
- `coach.max_workers` reached (default 3) or a worker hit
  `worker_turn_cap`/`worker_time_cap_s` — `agent_status` shows the table.

## Sessions & ranges

### Deploy hangs or fails

- Watch the session **Log** tab — Ludus build steps, role convergence and
  flag injection all land there.
- On a real engine, Ludus is the source of truth: service up? templates
  registered? `ludus templates list` on the host.
- `flag <id> inject FAILED` → guest agent problem on that VM (see below).
- Mock mode always completes — if mock hangs it's a backend bug.

### `agent/exec` failures / QGA timeouts on real engine

- Guest agent must be installed **and** running in the VM
  (`qemu-guest-agent`); stock Ludus templates ship it.
- Long multi-line exec payloads can wedge the virtio channel — pentrAIn
  writes scripts via the QGA **file API** and executes a short
  `timeout 55 sh /tmp/...` instead. If you see PVE REST errors mentioning
  *wide character*: non-ASCII content in a guest command path — scripts are
  intentionally ASCII-only.
- After snapshot rollback the agent needs a beat to come back — the backend
  waits for `agent/ping` before exec.

### Console black / disconnected

- The console proxies the **engine PVE's** `vncwebsocket` for the session's
  Kali VMID — engine credentials must work from the app.
- After a reset the ticket dies; the UI reconnects automatically on the new
  `ready_at`. The ⟳ button forces a fresh ticket.
- Persistent failure → check `engine.pve_*` creds; a **hard reset**
  allocates a new range/VMIDs if the VMID changed under you.

### Terminal tabs stay "waiting for kali agent"

- The reverse channel lives in `pentrain-telemetried` on the Kali VM — if
  telemetry works but terminals don't, check the unit there and that
  `/opt/pentrain-telemetried/telemetried.conf` contains `SHELL=1` (written by
  the backend at session setup; **target VMs intentionally don't get it**).
- The agent needs `python3-websockets` (`apt list --installed | grep
  websockets`) — the `pentrain_kali_agent` role installs it; a stale template
  predates the feature → rebuild the template.
- `journalctl -u pentrain-telemetried` shows `pentrain-shell` worker errors.
- Tabs keep reconnecting after reload — that is the design (tmux persists);
  a permanent "⚠" dot means the session left `ready`/`active`.

### No telemetry / checkpoints dead

`pentrain-telemetried.service` on the Kali VM must be running
(`systemctl status pentrain-telemetried`). The shell hook (`hook.sh`) logs
commands; the daemon ships them to `platform.api_url` + `/api/telemetry`
with the session token. If `platform.api_url` doesn't resolve from inside
the range, telemetry silently never arrives.

### Kali internet toggle misbehaves

- Enabling hot-plugs `net1` on `engine.kali_wan_bridge` (default `vmbr0`) —
  that bridge must actually reach LAN/internet.
- While up: the range default route is removed, DNS comes from the LAN,
  internal target names resolve via managed `/etc/hosts` entries — so
  `target01` still pings.
- Removing detaches `net1` first, lets NetworkManager settle, then restores
  range route/DNS — a small settle gap is normal.
- Wrong bridge → no DHCP lease: check `engine.kali_wan_bridge` matches your
  uplink bridge.

## Installer

| Symptom | Fix |
|---|---|
| Failure mid-run | Everything is in `installer/logs/install.log`; re-run `./install.sh --verbose` for raw Ansible output |
| Want a fresh run | The installer is idempotent — re-running resumes past done tasks; nothing to undo first |
| Ugly/no status board | Non-interactive shells get plain output; force with `PENTRAIN_UI=plain` or `NO_COLOR=1` |
| `direct` refuses to proceed | Host has existing VMs/CTs — either dedicate it or pass `--i-know-dedicated` after reading the warning |
| Windows/AD quests locked | Templates not built — re-run with `--with-templates` or build `win2022-server-x64-template` manually |

## Packs & content

| Symptom | Fix |
|---|---|
| New quest not in library | `pentrain pack-lint` → `pentrain sync-packs` (or Settings → *Sync quest packs*) |
| Role missing at deploy | Roles live on the **PVE host** — rsync to `/opt/pentrain/ansible-roles/` + `ludus ansible role add -d … -g`; see [ops.md — rolling out quests](ops.md#rolling-out-new-quests) |
| Changed quest not picked up | `quest.yaml` changes apply to **new** sessions — running sessions keep their deploy-time snapshot |

## WebUI

| Symptom | Fix |
|---|---|
| Settings shows `********` | Secret redaction — patch a real value to change, `********` keeps the stored one |
| "engine mock" everywhere | `engine.mode` = mock **or** missing PVE/Ludus creds — the engine falls back to MockProvider |
| Quest locked despite solves | Exam gate (needs *all* tier quests) or resource budget — hover the lock for `lock_reason` |

## Data & upgrades

| Task | Path |
|---|---|
| Backup | Stop the stack → copy `/data/pentrain.db` (volume `pentrain-data`) — all progress, scores, settings, chat live there |
| Upgrade | Pull → `pentrain build` → `pentrain up`; DB migrations run at backend start |
| Rotate `PENTRAIN_APP_SECRET` | **Don't** lightly — it seeds every flag derivation; live sessions' flags would stop validating |
