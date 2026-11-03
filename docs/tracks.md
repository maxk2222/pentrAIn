# Tracks & quests

**61 quests across 11 tracks**, organized in tiers 1–4. Quests ship a
briefing, coach checkpoints, staged hints and a `defense.md` (what broke, how
to detect it, how to fix it) — capstone quests are the exception: they go in
blind.

![Quest library](assets/screenshots/04-library.png)

## Progression rules

```mermaid
flowchart TD
    T1["tier 1 quests — always open"] -->|"solve ANY one"| T2["tier 2 quests"]
    T2 -->|"solve ANY one"| T3["tier 3 quests"]
    T1all["ALL tier-1 quests solved"] --> E1["tier-1 EXAM"]
    T2all["ALL tier-2 quests solved"] --> E2["tier-2 EXAM"]
    T3all["ALL tier-3 quests solved"] --> E3["tier-3 EXAM"]
    E1 -.->|"never counts as predecessor"| T2
```

- **Tier N quest** unlocks when **any** non-exam quest of tier N−1 in the same
  track is solved.
- **Exam** (`meta.exam: true`, **EXAM** badge) unlocks when **every** teaching
  quest of its track+tier is solved — the capstone for that tier.
- Exams never count as tier predecessors — solving the T1 exam alone does not
  open T2.
- A **capacity gate** additionally locks quests the host can't fit right
  now: `resources.gate_mode = live` (default) weighs each topology's
  *ballooning floor* — not nominal RAM — against free host RAM, CPU
  overcommit, disk, and whether every referenced template exists on the
  node. `static` falls back to `resources.max_*` budgets; `off` unlocks
  everything. Locked quests always name the reason (missing template,
  prerequisite, or capacity).

## The tracks

### 🐧 Linux Fundamentals — `linux-fundamentals` (8)

Host services, misconfigurations, privilege escalation — guided basics to
multi-host chains.

| Quest | Tier | Focus |
|---|---|---|
| First Foothold | 1 | Weak SSH creds → sudo misconfiguration |
| Sticky Bits | 1 | SUID binary reads any file as root |
| **Exam: The Onboarding Box** | 1 | Loot → shell → one SUID climb, no walkthrough |
| Privilege Chains | 2 | Leaked creds, GTFOBins sudo, writable cron — pick a route |
| Wildcard | 2 | `tar *` in root's cron — filenames are arguments |
| **Exam: The Maintenance Window** | 2 | Two privesc paths, find at least one |
| The Pivot | 3 | Web host is the only path to the DB — pivot through |
| **Exam: Supply Chain** | 3 | Three hosts deep, creds leak at every hop |

### 🌐 Web AppSec — `web-appsec` (12)

OWASP vulnerability classes from basics to chained auth-bypass.

| Quest | Tier | Focus |
|---|---|---|
| Damn Vulnerable | 1 | DVWA: LFI + uploads |
| Trusting Query | 1 | SQLi login bypass → data extraction |
| Committed | 1 | `.git` deployed to prod, "removed" credentials |
| **Exam: The Leaky Portal** | 1 | Source disclosure → shell |
| Juice Heist | 2 | Juice Shop recon + ftp easter egg + admin section |
| Gallery | 2 | Upload blacklist + MIME trust → www-data → root |
| Pressing Matters | 2 | WordPress + wpscan → theme editor → flag |
| **Exam: The Intranet** | 2 | Login bypass + upload bypass + shell in one app |
| Broken Trust | 3 | SSRF into an internal API |
| Signed & Confused | 3 | JWT secret → IDOR → admin |
| **Exam: The Reporting API** | 3 | JWT + IDOR + API → root shell |
| Split-Second | 4 | 0.CL request smuggling: nginx front-end vs. Flask back-end desync |

### 📡 Network & Recon — `network-recon` (8)

Discovery, enumeration, segmentation, pivoting across routed networks.

| Quest | Tier | Focus |
|---|---|---|
| The Perimeter | 1 | Five open services, creds follow from enumeration |
| Open Shares | 1 | Guest SMB share → runbook full of creds |
| **Exam: Neighborhood Watch** | 1 | Enumerate everything → leaked creds → root |
| Zone Out | 2 | AXFR giveaway, factory SNMP, anonymous TFTP |
| Behind the Firewall | 2 | Second host only trusts the first — pivot |
| **Exam: Perimeter Audit** | 2 | Edge box gossips; the target only listens to it |
| Three Hops Deep | 3 | DMZ → app tier → data tier, chained pivots |
| **Exam: Three Doors Down** | 3 | Every protocol from the tier pays off |

### 🏢 Active Directory — `active-directory` (7)

Domain attacks from a single DC to multi-forest corporate networks.

| Quest | Tier | Focus |
|---|---|---|
| Domain Join | 1 | One DC, one roastable service account |
| No Preauth | 1 | AS-REP roast without any credential |
| **Exam: First Contact** | 1 | Kerberoast + AS-REP + SYSVOL loot |
| Lateral Pressure | 2 | File server → workstation → DC, creds walk |
| **Exam: The Corp Lan** | 2 | Full corp chain + a surprise roastable |
| Enterprise | 3 | Flagship: 2 DCs, 2 workstations, nothing → Enterprise Admin |
| **Exam: Domain Takeover** | 3 | The complete kill chain, timed |

> [!WARNING]
> AD quests need **Windows templates** (`win2022-server-x64-template`,
> `win11-22h2-x64-template`) — built via `install.sh --with-templates` or a
> manual Ludus template build (hours, tens of GB). T3 wants ~48 GB RAM.
> Details: [ops.md — Windows / AD quests](ops.md#windows--active-directory-quests).

### 🔍 Forensics — `forensics` (7)

Log triage, disk artifacts, intrusion timelines on attacked ranges.

| Quest | Tier | Focus |
|---|---|---|
| The Break-In | 1 | Logs → intruder's stash → prove persistence |
| Wiretap | 1 | Replay credentials straight out of a NIDS capture |
| **Exam: Black Box** | 1 | One capture + one host → the trail |
| Post Mortem | 2 | SQLi in access.log → webshell → exfil archive |
| **Exam: Full Report** | 2 | The implant the attacker never mentioned |
| Correlated | 3 | Three-host intrusion: edge → app → DB exfil |
| **Exam: The Whole Incident** | 3 | Correlate web02 pop with the quiet db02 touch |

### 💻 Scripting & Automation — `scripting` (7)

Bash and Python glue code — the output artifact itself is often the flag
(`vm: kali` command flags verify files *you* produced).

| Quest | Tier | Focus |
|---|---|---|
| Recon.sh | 1 | First recon script → machine-readable report |
| **Exam: Report Generator** | 1 | One script, three data sources, one report |
| Nonce Grinder | 2 | Proof-of-work token API — brute-force the PIN |
| **Exam: Evidence Pipeline** | 2 | Pull capture → crack creds → land proof → flag |
| Blind Pipe | 3 | Command injection in a diagnostics CGI — scripted |
| Hands-Free Pivot | 3 | One script: upload bypass + cred theft + SSH pivot |
| **Exam: Zero-Touch Vault** | 3 | The whole kill chain, zero clicks |

### 📶 Wireless — `wifi` (6)

802.11 labs simulated **inside the target VM** with `mac80211_hwsim` — no
physical radios. You SSH from Kali into the lab VM (`wifi` user, creds in the
briefing); attack tooling lives on the VM itself.

| Quest | Tier | Focus |
|---|---|---|
| Captured Keys | 1 | Crack a packaged WPA handshake → AP admin |
| **Exam: Backup Channel** | 1 | Second capture + site survey mismatch |
| Live Air | 2 | Deauth a live client → handshake → crack PSK |
| **Exam: Ops Channel** | 2 | Live WPA2 + encrypted config backup |
| No Client Needed | 3 | PMKID leak + a rogue AP that shouldn't exist |
| **Exam: Dual Band** | 3 | Two networks: PMKID + full handshake cycle |

Packaged captures (`files/*.cap`) are real hwsim-generated handshakes —
regeneration: [ops.md — wireless labs](ops.md#wireless-hwsim-labs).

### 🏠 Home Lab — `home-lab` (1)

| Quest | Tier | Focus |
|---|---|---|
| Home Field Advantage | 1 | Point Kali at **your own LAN**: discovery → enumeration → read-only access checks → evidence → assessment report |

> [!CAUTION]
> This track attacks your real network over the Kali `net1` uplink. The coach
> enforces `lan.scope_cidr` (default: auto-detected /24 from the DHCP lease),
> read-only probes, and a shared action budget — but the ROE is on you:
> only devices you own, no DoS, no aggressive brute force.

### ☁️ Cloud-Native — `cloud-native` (1)

Kubernetes attack paths on a real `kind` cluster — from a pod debug
endpoint to node compromise.

| Quest | Tier | Focus |
|---|---|---|
| Soft-Schedule | 1 | Pod RCE → over-permissive service account → secrets → privileged pod → host flag |

### 🤖 AI Security — `ai-security` (1)

LLM application attacks — OWASP LLM Top-10 against a deterministic
embedded assistant (no external API key needed).

| Quest | Tier | Focus |
|---|---|---|
| AskOps | 1 | Prompt injection: guard bypass → system-prompt leak → indirect injection via trusted docs → tool abuse |

### 👑 Capstone — `capstone` (3)

| Quest | Tier | Focus |
|---|---|---|
| Nordmarkt Feinkost | 2 | Single-box engagement: web enum → backup leak → foothold → internal API cmd-injection → DB LOAD_FILE → cron privesc → written report |
| Nordwind Logistics | 3 | Full engagement: recon → source leak → foothold → two pivots → API compromise → DB creds → hash crack → privesc → written report |
| Cloudburst | 4 | Cloud-native kill chain: edge SSRF → k8s API abuse → privileged escape → node loot — end to end |

> [!NOTE]
> Capstone quests ship **no hints, no checkpoints, no cheatsheet and no
> coach briefing** — the engagement letter is all you get. They double as
> the full-auto agent benchmark: see [agent-eval.md](agent-eval.md).

## Scoring

```mermaid
flowchart LR
    F["+ flag points<br/>Σ(flag.points)"] --> S
    TB["+ time bonus<br/>decays linearly: full at t=0,<br/>half at par_s, 0 at 2×par"] --> S
    H["− hint costs"] --> S
    T["− takeover_cost<br/>if the coach executed anything"] --> S
    S["final score → quest leaderboard<br/>+ persisted breakdown + duration"]
```

- **Flag points** — every flag carries `points`; their sum is the score's
  base. (`scoring.base` in quest.yaml is a display reference, not added.)
- **Time bonus** — `time_bonus_max` scaled by `1 − t/(2·par_s)`: full
  only on an instant clear, half at par, zero at 2×par.
- **Hint costs** — shown up front per hint (−25, −50, …).
- **Takeover cost** — a flat `takeover_cost` once the coach executes at
  least one command (autonomy 4), not per action.
- **Breakdown** — every attempt persists its components (`flags`,
  `time_bonus`, `hint_cost`, `takeover_penalty`, `par_s`); hover a score
  on any leaderboard to see them, and the global board shows the best
  run's duration.
- **Solve style** — the leaderboard shows per-attempt aid chips:
  `sheet`, `panel`, `coach`, `tips`, `hint`, `takeover`. Solving with no
  assistance earns the `solo` badge.

Per-quest and global leaderboards: **Leaderboard** page and
`GET /api/quests/{id}/leaderboard`.
