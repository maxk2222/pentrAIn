# Quest authoring

A quest is a directory under `content/packs/<track>/<quest-id>/`:

```
linux-t1-first-foothold/
├── quest.yaml        # the whole contract — topology, flags, hints, coach, scoring
├── briefing.md       # shown in the UI before/during the quest (GFM)
├── defense.md        # what broke, how to detect it, how to fix it
├── cheatsheet.md     # optional — quick reference shown in the session side panel
└── coach_context.md  # private briefing for the coach (never shown to the trainee)
```

A track may also carry `content/packs/<track>/cheatsheet.md` — a shared
reference card (tool syntax for the discipline) that the in-session panel
renders under "Track reference" for every quest in the track.

Validate with `python scripts/lint_packs.py` — CI runs it on every push.
Missing `cheatsheet.md` is a warning, not an error.

## Cheatsheet conventions

The cheatsheet panel sits next to the console and the coach — it is
**reference, not hint**: tool syntax, host inventory, concepts worth
remembering. Spoiler policy:

- **Allowed**: commands with placeholders (`ssh -J user@<hop>`), which tools
  apply, non-secret host descriptions, "watch for X" nudges.
- **Not allowed**: flag paths, credentials, the actual vulnerable parameter,
  anything `hints:` would charge points for.

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
    ram_gb: 6                             # ballooning max; ram_min_gb sets the floor
    ram_min_gb: 3                         # optional — kali defaults 3, targets ram_gb/2
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
`ram_gb` is the ballooning ceiling and `ram_min_gb` the floor Proxmox may shrink
to under pressure; `requirements.min_ram_gb` should cover the sum of `ram_gb`
plus ~2G for the implicit router.

### Flags

```yaml
flags:
  - id: user-flag               # stable key — flag secrets derive from (session, id)
    name: "User flag — read user.txt"
    kind: file                  # file | command
    points: 100
    vm: target01
    file_path: /home/student/user.txt
```

Flag values are randomized per session (HMAC over the session's `flag_seed`).
The platform injects them **after** deploy via the qemu guest agent
(`flags_svc.inject_flags` → `pve.agent_write_file`); the backend verifies
submissions. Roles must therefore **never** write `pentrAIn{...}` files —
only create the vulnerability and any directory the flag file lands in.

- `kind: file` — backend writes `{secret}` to `file_path` on `vm`. With
  `container: <name>` it goes through `docker exec` into that container.
- `kind: command` — backend runs `command.cmd` on `command.vm` and compares
  stdout to the flag (substring `expect` or exitcode). The check runs a
  **POSIX shell** — not valid on `windows:`/`linux: false` VMs (linted).
- Windows VMs: use `kind: file` only; the guest agent handles `C:\...` paths.

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
- Do **not** plant flag content — the platform injects `pentrAIn{...}`
  secrets post-deploy via the guest agent. Roles may `file: state=directory`
  the flag's parent dir so a restricted path still resolves.
- The Kali box always gets `pentrain_kali_agent` (telemetry sidecar + shell
  hook). Do not remove it — checkpoints and the coach die silently without it.
  Its files mirror `telemetry-agent/`; the linter fails on drift.

### Windows / Active Directory quests

- `topology.vms[].linux: false` + `windows: {...}` + `domain: {...}` are
  passed through to Ludus verbatim — use `win2022-server-x64-template` /
  `win11-22h2-x64-template` (needs a `--with-templates` build; see ops.md).
- Ludus domain schema (verified):
  `domain: {fqdn: corp.pentrain.local, role: primary-dc|alt-dc|member}` —
  `primary-dc` promotes the forest root, `alt-dc` adds a replica,
  `member` joins a workstation.
- `windows:` subkeys: `sysprep: true`, `install_additional_tools`,
  `gpos: [name]` — or top-level `gpos: [...]` on the VM, which the compiler
  folds into `windows.gpos` (linted: linux VMs can't take gpos).
- Only `kind: file` flags — `kind: command` runs a POSIX shell and will
  never execute on Windows (the pack linter rejects the combination).
- Flag paths are Windows-style: `file_path: "C:\\flags\\domain-admin.txt"`.
- `ip_last_octet: 254` is reserved for the range router (linted).
- Users, OUs and misconfig belong in the quest's `pentrain_ad_*` roles
  (`community.windows.*` / `ansible.windows.*` modules over winrm).

### Checklist before committing a quest

- [ ] `python scripts/lint_packs.py` — 0 errors
- [ ] Roles are idempotent and use `validate:` on config writes
- [ ] Every flag's `vm` exists in `topology.vms`; `file_path` parent dirs
      are created by a role (or default to `/root`, `C:\flags`)
- [ ] Checkpoint regexes match *real* commands a trainee would type
- [ ] `requirements` reflect the sum of VM RAM/CPUs + kali — `check_unlock`
      hard-blocks quests that exceed the admin-configured budget
- [ ] `briefing.md` states the goal without leaking the path;
      `defense.md` has detect+fix+verify for every vulnerability;
      `cheatsheet.md` stays spoiler-free (syntax/concepts only)
- [ ] `coach_context.md` lists the intended path and common wrong turns

## Testing a pack

0. `python scripts/new_quest.py <track> <quest-id> --tier N --role` — scaffolds
   the quest dir + optional role skeleton and validates immediately.
1. `python scripts/lint_packs.py` — schema + agent-sync check.
2. `docker compose -f engine/docker-compose.dev.yml up` — MockProvider
   accepts every topology; the full UI flow (deploy → flags → reset) is
   exercisable without a hypervisor.
3. Real validation needs a Ludus host: deploy the quest, verify the role
   converges, flags submit, checkpoints fire on the right commands.
