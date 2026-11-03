<p align="center">
  <img src="docs/assets/logo.png" alt="pentrAIn" width="380" />
</p>

<h1 align="center">pentrAIn</h1>

<p align="center">
  <strong>A self-hosted pentest training platform — quests, a live AI coach, and a browser-based Kali, on your own Proxmox.</strong>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="docs/README.md">Documentation</a> ·
  <a href="docs/architecture.md">Architecture</a> ·
  <a href="docs/tracks.md">Quest catalog</a> ·
  <a href="docs/SECURITY.md">Security</a>
</p>

<p align="center">
  <img alt="stack" src="https://img.shields.io/badge/stack-FastAPI%20·%20React%2019%20·%20SQLite-1f6feb?style=flat-square" />
  <img alt="engine" src="https://img.shields.io/badge/engine-Proxmox%20VE%20%2B%20Ludus-e9761a?style=flat-square" />
  <img alt="quests" src="https://img.shields.io/badge/quests-57%20in%209%20tracks-2ea44f?style=flat-square" />
  <img alt="coach" src="https://img.shields.io/badge/coach-4%20autonomy%20levels%20·%20tool%20calling-8250df?style=flat-square" />
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square" />
</p>

---

pentrAIn turns a Proxmox host into a guided offensive-security range. Pick a
quest, get a fresh isolated lab — router, targets, and a real Kali desktop
streamed into your browser — with an AI coach watching your command stream
and adapting to how you work.

> [!IMPORTANT]
> **Active development — read before installing.**
>
> - **Requires a Proxmox host.** Either a fresh, dedicated machine
>   (`--mode direct`) or an existing PVE server (`--mode nested`, runs the
>   whole range inside one VM with nested virtualization).
> - **Not every quest runs on every host.** Quests are gated on the host's
>   live capacity — small hosts skip the RAM-hungry ones (Active Directory
>   needs the most; the unlock list always says why a quest is locked).
> - **Active Directory is untested** — the AD track and its Windows
>   templates have not been verified on a live range yet.
> - **No GPU integration yet** — the Kali worker is CPU-only for now.

<p align="center">
  <img src="docs/assets/gifs/quest-start.gif" alt="starting a quest" width="780" />
</p>

## Features

<table>
  <tr>
    <td width="50%">
      <h3>🗺️ Quest library</h3>
      <b>57 quests in 9 tracks</b> — Linux, web appsec, network recon, AD,
      forensics, scripting, wireless, home-lab, capstone. Tiered progression,
      exam capstones, staged hints that cost points.
    </td>
    <td width="50%">
      <h3>🖥️ Browser workspace</h3>
      A real <b>Kali desktop over noVNC</b>, objectives and flags on the
      left, coach on the right — resizable panels, notes, cheatsheets,
      network map, live stats.
    </td>
  </tr>
  <tr>
    <td>
      <h3>🤖 AI coach</h3>
      Watches your telemetry and answers with streamed Markdown. <b>Four
      autonomy levels</b> — Observer → Mentor → Copilot → Autonomous — from
      silent hints to driving your Kali in a visible tmux, including
      <b>parallel worker agents</b>.
    </td>
    <td>
      <h3>🎯 Dynamic flags</h3>
      <code>pentrAIn{...}</code> secrets are <b>HMAC-derived per session</b>
      and injected post-deploy via the QEMU guest agent — soft resets
      re-randomize them, walkthroughs can't be memorized.
    </td>
  </tr>
  <tr>
    <td>
      <h3>🛡️ Defense-first</h3>
      Every quest ships a <code>defense.md</code>: what you exploited, how
      to detect it, how to fix it — training for both sides of the wire.
    </td>
    <td>
      <h3>🏆 Scoring</h3>
      Per-quest leaderboards with time bonuses, hint costs, takeover
      penalties — and a <b>solve-style badge</b> recording how much help
      you took (<code>solo</code> is the flex).
    </td>
  </tr>
  <tr>
    <td>
      <h3>🌐 Kali uplink on demand</h3>
      One click hot-plugs a second NIC onto your LAN bridge — internet for
      <code>apt</code> and wordlists, while targets stay isolated.
    </td>
    <td>
      <h3>🧰 Guided Kali builder</h3>
      Clone a base template, customize it through the web console,
      finalize — every future session boots <b>your</b> Kali.
    </td>
  </tr>
</table>

## The coach, in one picture

```mermaid
flowchart TB
    subgraph MODE["one coach, four modes — switched live per session"]
        direction LR
        A["1 · Observer<br/>watch + chat only"] --> B["2 · Mentor<br/>+ mark checkpoints"]
        B --> C["3 · Copilot<br/>+ command chips you confirm"]
        C --> D["4 · Autonomous<br/>+ drives Kali tmux · workers"]
    end
    MODE --> GATE{"policy gate<br/>silence by default<br/>budgets · scope"}
    GATE --> LLM["LLM turn — tool schema rebuilt<br/>from level + Sub toggle"]
    LLM --> MAIN["main feed<br/>coach messages · exec reports"]
    LLM <-->|"spawn_agent → collect_agent<br/>(level 4 + Sub)"| W["workers w1–w3<br/>exec-only toolset<br/>own tmux windows"]
    W -.->|"meta.agent tagged"| FEED["per-worker feeds<br/>clickable chips above the composer"]
```

## Screenshots

<p align="center">
  <img src="docs/assets/screenshots/07-session-workspace.png" alt="session workspace" width="780" />
</p>

<p align="center">
  <img src="docs/assets/gifs/coach-chat.gif" alt="coach chat" width="49%" />
  <img src="docs/assets/gifs/flag-solve.gif" alt="flag solve" width="49%" />
</p>

<p align="center">
  <img src="docs/assets/gifs/agent-autonomous.gif" alt="coach in autonomous mode — live tmux on the Kali desktop" width="780" />
</p>

<details>
<summary><b>More screenshots</b></summary>
<br/>

| Dashboard | Library |
|---|---|
| ![dashboard](docs/assets/screenshots/03-dashboard.png) | ![library](docs/assets/screenshots/04-library.png) |

| Quest briefing | Settings |
|---|---|
| ![quest](docs/assets/screenshots/05-quest-detail.png) | ![settings](docs/assets/screenshots/12-settings.png) |

| Autonomous session | Panels tour |
|---|---|
| ![autonomous](docs/assets/screenshots/13-session-autonomous.png) | ![panels](docs/assets/gifs/workspace-panels.gif) |

| Internet toggle | |
|---|---|
| ![internet](docs/assets/gifs/internet-toggle.gif) | |

</details>

## Architecture

```mermaid
flowchart LR
    subgraph Browser["🖥️ Browser"]
        FE["React SPA<br/>noVNC console"]
    end
    subgraph App["pentrain-app"]
        BE["FastAPI backend"]
        CO["coach agent"]
        DB[("SQLite")]
    end
    subgraph Engine["Engine: Proxmox VE + Ludus"]
        subgraph Range["isolated range /24"]
            K["Kali + telemetry"]
            T["target VMs"]
        end
    end
    FE -->|REST · WS · VNC| BE
    CO -->|service API| BE
    BE --> DB
    BE -->|ranges · VMs · QGA| Engine
    K -->|telemetry| BE
    CO -.->|OpenAI-compatible| LLM["🧠 your LLM"]
```

[Ludus](https://ludus.cloud/) is consumed as an **external range engine**
over its REST API — pentrAIn doesn't vendor or modify it. The coach talks to
any OpenAI-compatible endpoint; a self-hosted model keeps everything
on-prem.

Deep dive: [docs/architecture.md](docs/architecture.md) · decisions:
[docs/adr/](docs/adr/)

## Quickstart

Requires a Proxmox VE host (dedicated, or any PVE that can host one large
nested VM) and Ansible ≥ 2.15:

```bash
cd installer
cp inventory.example.yml inventory.yml   # your PVE host + API token
./install.sh --mode nested               # or: --mode direct
```

- **`nested`** (default): builds a `pentrain-engine` VM — nested Proxmox +
  Ludus + app VM — on your existing homeserver. Leaves everything else
  untouched.
- **`direct`**: installs Ludus on the target PVE host itself — the host must
  be **dedicated** to pentrAIn.

Then open `https://<pentrain-app-ip>`, walk the setup wizard, and start
*Linux Fundamentals → First Foothold*.

→ Full guide: [docs/getting-started.md](docs/getting-started.md)

## Development (no Proxmox needed)

```bash
make dev   # backend + coach + frontend against MockProvider
```

MockProvider simulates the full range lifecycle so the whole app — sessions,
flags, coach plumbing, leaderboards — is testable on a laptop.

→ [docs/development.md](docs/development.md)

## Documentation

| | |
|---|---|
| 🚀 [Getting started](docs/getting-started.md) | Install modes, setup wizard, first quest |
| 🖥️ [Workspace](docs/workspace.md) | Console, panels, flags, resets, Kali internet |
| 🤖 [AI coach](docs/coach.md) | Autonomy levels, tools, subagents, guardrails |
| 🗺️ [Tracks & quests](docs/tracks.md) | All 9 tracks, exams, scoring |
| 🏗️ [Architecture](docs/architecture.md) | Components, lifecycle, event flows, data model |
| 🔌 [API reference](docs/api-reference.md) | REST + WebSocket surface |
| ⚙️ [Configuration](docs/configuration.md) | Every settings key + env var |
| 🛠️ [Ops runbook](docs/ops.md) | Logs, resets, backups, pack rollout |
| 🩺 [Troubleshooting](docs/troubleshooting.md) | Symptom → cause → fix |
| 🧪 [Development](docs/development.md) | Dev loop, tests, layout |
| ✍️ [Quest authoring](docs/quest-authoring.md) | `quest.yaml`, roles, checkpoints |
| 🔒 [Security](docs/SECURITY.md) | Threat model, isolation, guardrails |

## Repo layout

| Dir | What |
|---|---|
| `backend/` | FastAPI core: quests, sessions, flags, scoring, settings, WS hub, console proxy, telemetry ingest |
| `coach/` | Coach agent service (observe → state → policy → act) |
| `frontend/` | React 19 + Vite + TS + Tailwind v4 |
| `content/` | Quest packs + `pentrain_*` Ansible roles + pack linter |
| `installer/` | Ansible: `--mode nested`/`direct` full bootstrap |
| `engine/` | App-VM docker-compose stack |
| `telemetry-agent/` | `pentrain-telemetried` — in-Kali command-stream sidecar |
| `cli/` | `pentrain` admin CLI (`doctor`, `pack-lint`, …) |
| `docs/` | Full documentation, ADRs, media pipeline |

## Security

Deliberately vulnerable VMs run here. Read
[docs/SECURITY.md](docs/SECURITY.md) before exposing anything. Default
posture: isolated ranges (Ludus testing mode), no public exposure, secrets
server-side only.

## License

Apache-2.0 — see [LICENSE](LICENSE). Ludus (AGPL) is consumed as an external
service via its API only.
