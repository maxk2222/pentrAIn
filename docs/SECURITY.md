# Security notes

pentrAIn runs **deliberately vulnerable machines**. That is the product. The
security posture therefore focuses on containing them — the range is the
blast radius, not your LAN.

## Threat model

| Asset | Exposure |
|---|---|
| Range VMs | Intentionally exploitable; treat every VM as hostile |
| Session Kali | Trainee-controlled; also executes coach-issued commands (autonomy 4) |
| pentrain-app | Holds PVE API tokens, LLM key, user credential, flag seeds |
| Engine PVE host | Full VM control — a compromised app VM is a hypervisor compromise |

## Isolation (default posture)

- **Ludus testing mode** puts each range behind its own router VM on a
  dedicated /24 with no route to the lab LAN. Internet access for ranges is
  cut by default.
- Quest networks are per-range VLANs, not shared bridges.
- The app UI is meant for **LAN access only**. Do not port-forward it to the
  internet. If remote access is needed, front it with a VPN or an
  authenticated reverse proxy.

## Authentication

- Single-admin web UI: password → **scrypt** hash (`scrypt$N$salt$digest`)
  stored in settings, constant-time verification, bearer token in
  `localStorage` on the client.
- `POST /api/setup/complete` is open **only until the first admin password is
  set**; afterwards it requires the bearer token (takeover guard).
- Coach service ↔ backend uses `PENTRAIN_COACH_SERVICE_TOKEN` — set a real
  value; the default `dev-coach-token` prints a startup warning for a reason.
- Telemetry ingest uses a **per-session token** derived at deploy time — a
  range VM cannot impersonate another session's event stream.
- `APP_SECRET` signs nothing else in v1 but must be non-default for any
  non-lab deployment.

## Coach command execution

The coach can run commands inside the session Kali. Guard rails:

- Autonomy levels 1–3 never execute — suggestions require an explicit user
  click (`suggest_command` → confirm) and run visibly.
- Level 4 executes **visibly** in a `pentrain-coach` tmux session so the
  trainee sees what is typed.
- Denied/blocked commands never reach the VM; per-session `action_budget`
  caps executions; daily LLM token budget is enforced service-wide.
- Telemetry is treated as **untrusted data** — the prompt explicitly forbids
  executing instructions found inside command output.

## Secrets

- `llm.api_key`, PVE tokens and the admin hash are stored server-side
  (`get_secret` settings) and are **never rendered into the coach context**
  — `flag_seed` (the HMAC seed behind all flag secrets) is also excluded.
- Nothing secret is logged; coach LLM prompts contain topology/telemetry
  context but no credentials or flag values.
- `installer/.secrets/` holds generated secrets — it is gitignored; do not
  commit it.

## Reporting

This is a training lab, not a hardened product. If you find a real
vulnerability in the platform itself (not the intended quest VMs), please
open a private security advisory rather than a public issue.
