# Quest authoring

A quest is a directory under `content/packs/<track>/<quest-id>/`:

```
linux-t1-first-foothold/
├── quest.yaml        # the whole contract — topology, flags, hints, coach, scoring
├── briefing.md       # shown in the UI before/during the quest (GFM)
├── defense.md        # what broke, how to detect it, how to fix it
└── coach_context.md  # private briefing for the coach (never shown to the trainee)
```

Validate with `python scripts/lint_packs.py` — CI runs it on every push.

## quest.yaml

```yaml
apiVersion: pentrain/v1
kind: Quest
meta:
  id: linux-t1-first-foothold     # unique, kebab-case, matches the dir name
  track: linux-fundamentals       # groups quests; ordering via `tier`
  tier: 1                         # progression within the track
  title: "First Foothold"
  version: 1
display:
  tagline: "SSH in with weak creds, escalate via a sudo misconfiguration."
requirements:
  min_ram_gb: 12                  # rejected at session start if under the resource cap
  min_vcpus: 6
  min_disk_gb: 80
  est_deploy_min: 8               # honest estimate — deploys take minutes
```

### Topology

```yaml
topology:
  kali:
    template: kali-x64-desktop-template   # Ludus template name
    ram_gb: 8
    cpus: 4
  vms:
    - name: target01
      template: debian-12-x64-server-template
      ram_gb: 2
      cpus: 2
      vlan: 10                            # optional; defaults to the range VLAN
      ip_last_octet: 21                   # stable .21 inside the range /24
      roles: [pentrain_linux_t1]          # Ludus ansible roles → vulnerabilities
```

The Kali VM is implicit per session — add every other box under `vms`.
`ip_last_octet` gives deterministic addresses for briefings and checkpoints.

### Flags

```yaml
flags:
  - id: user-flag               # stable key — flag secrets derive from (session, id)
    name: "User flag — read user.txt"
    kind: file                  # file | command | web | manual
    points: 100
    vm: target01
    file_path: /home/student/user.txt
```

Flag values are randomized per session (HMAC over the session's `flag_seed`);
the role plants them during deploy, the backend verifies submissions. Never
hard-code `PENTRAIN{...}` values in pack files — use the flag placeholders
the `pentrain_*` roles expose.

### Hints

```yaml
hints:
  - id: h1
    cost: 25                    # score penalty when the trainee opens it
    stage: recon                # free-form grouping label
    text: "Start with what you know: credentials were leaked in the briefing."
```

Order matters — hints escalate within their stage.

### Coach

```yaml
coach:
  briefing_ref: coach_context.md
  checkpoints:
    - id: cp-ssh
      name: "Logged in as student"
      detect: { command_match: "ssh student@" }   # regex on the command stream
      hint_after_s: 600                           # escalation floor if missed
  escalation:
    observe_grace_s: 120    # silence window after session start
    nudge_s: 360            # stuck this long → coach may nudge
    hint_s: 720             # stuck this long → coach may offer a real hint
```

Checkpoints let the coach see *progress* without an LLM call: the command
stream is matched silently, and a hit produces a cheap template ack. Write
patterns that match intent (`nmap|ss |netstat`) rather than exact syntax —
trainees type many equivalent commands.

`coach_context.md` is the coach's private knowledge: intended solve path,
common dead ends, which hints map to which stage. It is **not** shown in the
UI — but assume a sufficiently capable trainee could extract it from the
model, so keep real flag values out of it anyway.

### Scoring

```yaml
scoring:
  base: 300
  time_bonus_max: 150
  par_s: 900             # finishing under par adds bonus, decaying to 0 at 2×par
  takeover_cost: 100     # penalty per coach takeover action (autonomy 4)
```

## Ansible roles

Per-quest vulnerability setup lives in `content/ansible-roles/pentrain_*/`.
Ludus applies `roles: [...]` to each VM during deploy. Conventions:

- Role name in `quest.yaml` must match the role directory.
- Idempotent tasks — ranges get soft-reset (snapshot rollback), but roles may
  also re-run after hard resets.
- Flag files are planted with content `{{ pentrain_flag('<flag-id>') }}` —
  the lookup is provided by the platform at deploy time.
- The Kali box always gets `pentrain_kali_agent` (telemetry sidecar + shell
  hook). Do not remove it — checkpoints and the coach die silently without it.
  Its files mirror `telemetry-agent/`; the linter fails on drift.

## Testing a pack

1. `python scripts/lint_packs.py` — schema + agent-sync check.
2. `docker compose -f engine/docker-compose.dev.yml up` — MockProvider
   accepts every topology; the full UI flow (deploy → flags → reset) is
   exercisable without a hypervisor.
3. Real validation needs a Ludus host: deploy the quest, verify the role
   converges, flags submit, checkpoints fire on the right commands.
