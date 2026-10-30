#!/usr/bin/env python3
"""Scaffold a new PenTrAIn quest pack.

Creates content/packs/<track>/<quest-id>/ with a validated quest.yaml skeleton,
briefing/defense/coach_context stubs, and optionally an Ansible role skeleton.

Usage:
    python scripts/new_quest.py <track> <quest-id> [--tier N] [--title "..."] [--role]

Example:
    python scripts/new_quest.py network-recon net-t1-services --tier 1 --role
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

QUEST_YAML = """\
apiVersion: pentrain/v1
kind: Quest
meta:
  id: {quest_id}
  track: {track}
  tier: {tier}
  title: "{title}"
  version: 1
display:
  tagline: "{tagline}"
requirements:
  min_ram_gb: 12          # kali (8G) + targets - keep realistic, check_unlock enforces it
  min_vcpus: 6
  min_disk_gb: 80
  est_deploy_min: 10
  # needs_windows: true   # set when any vm uses a windows template
topology:
  kali:
    template: kali-x64-desktop-template
    ram_gb: 8
    cpus: 4
  vms:
    - name: target01
      template: debian-12-x64-server-template
      ram_gb: 4
      cpus: 2
      vlan: 10
      ip_last_octet: 21
      roles: [{role}]
flags:
  - id: user-flag
    name: "User flag"
    kind: file                  # injected post-deploy via qemu-guest-agent
    points: 100
    vm: target01
    file_path: /home/student/user.txt
  - id: root-flag
    name: "Root flag"
    kind: file
    points: 200
    vm: target01
    file_path: /root/root.txt
  # kind: command runs a POSIX shell check on the target - NOT for windows vms:
  #   command: {{vm: target01, cmd: "...", expect: "..."}}
hints:
  - id: h1
    cost: 25
    stage: recon
    text: "TODO: gentle nudge toward the first enumeration step."
  - id: h2
    cost: 50
    stage: exploit
    text: "TODO: point at the vulnerability class without naming the exploit."
  - id: h3
    cost: 75
    stage: privesc
    text: "TODO: nearly direct answer for trainees who are truly stuck."
coach:
  briefing_ref: coach_context.md
  checkpoints:
    - id: cp-recon
      name: "Performed initial enumeration"
      detect: {{ command_match: "(nmap|ss |netstat)" }}
      hint_after_s: 600
    - id: cp-foothold
      name: "Gained initial access"
      detect: {{ command_match: "(ssh |hydra|nc )" }}
      hint_after_s: 900
  escalation: {{ observe_grace_s: 180, nudge_s: 480, hint_s: 900 }}
scoring:
  base: 500
  time_bonus_max: 200
  par_s: 1800
  takeover_cost: 150
"""

BRIEFING_MD = """\
# {title}

> **Track**: {track} · **Tier**: {tier} · **Estimated time**: ~XX min

## Scenario

TODO: 2-3 sentences of narrative framing. Who are you, what is the target,
why does this engagement exist?

## Objectives

1. TODO: objective tied to flag `user-flag`
2. TODO: objective tied to flag `root-flag`

## Environment

- **Kali**: your attack workstation (desktop opens in the browser tab)
- **target01**: TODO describe what the trainee can observe (IP, services)

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `PenTrAIn{{...}}` - submit them in the Flags panel.
"""

DEFENSE_MD = """\
# Defense notes - {title}

How the vulnerabilities in this quest are detected and fixed.

## Vulnerability 1 - TODO name

- **Weakness**: TODO what was misconfigured
- **Detect**: TODO log/file/alert that reveals exploitation
- **Fix**: TODO concrete hardening step
- **Verify**: TODO command/test that proves the fix

## Vulnerability 2 - TODO name

- **Weakness**: ...
- **Detect**: ...
- **Fix**: ...
- **Verify**: ...
"""

COACH_CONTEXT_MD = """\
# Coach context - {title}

Ground truth for the coaching agent. Never quote this verbatim to the trainee.

## Intended path

1. TODO step -> expected commands/tools
2. TODO step -> expected commands/tools
3. TODO step -> flag location

## Key facts (do not leak early)

- TODO: credentials, hidden paths, flag locations the coach may reference only
  at escalation stage 2-3

## Common wrong turns

- TODO: what trainees typically try that doesn't work, and how to redirect them

## Forensics/blue-team angle (optional)

- TODO: for forensics quests - where the planted artifacts live
"""

ROLE_TASKS = """\
---
# {role} - quest target for {quest_id}
# Idempotent tasks only; use `validate:` on config writes; notify handlers
# for service restarts. Flags are injected post-deploy by the platform -
# do NOT write PenTrAIn{{...}} files here.
- name: TODO first task
  ansible.builtin.debug:
    msg: "replace me"
"""

ROLE_HANDLERS = """\
---
# - name: restart sshd
#   ansible.builtin.service:
#     name: ssh
#     state: restarted
"""


def _kebab(s: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("track", help="track slug, e.g. network-recon")
    ap.add_argument("quest_id", help="quest dir + meta.id, kebab-case, e.g. net-t1-services")
    ap.add_argument("--tier", type=int, default=1)
    ap.add_argument("--title", default=None, help='display title, e.g. "First Foothold"')
    ap.add_argument("--role", action="store_true", help="also scaffold content/ansible-roles/pentrain_<id>")
    args = ap.parse_args()

    for label, val in (("track", args.track), ("quest id", args.quest_id)):
        if not _kebab(val):
            ap.error(f"{label} must be kebab-case ([a-z0-9-]), got {val!r}")
    if not (1 <= args.tier <= 9):
        ap.error("--tier must be 1..9")

    sys.path.insert(0, str(REPO / "backend"))
    try:
        from app.services.packs import TRACK_TITLES
        if args.track not in TRACK_TITLES:
            print(f"warning: '{args.track}' is not a known track ({', '.join(sorted(TRACK_TITLES))})")
    except ImportError:
        pass

    qdir = REPO / "content" / "packs" / args.track / args.quest_id
    if qdir.exists():
        ap.error(f"{qdir} already exists")

    title = args.title or args.quest_id.split("-", 2)[-1].replace("-", " ").title()
    tagline = f"TODO: one-line hook for the library card (tier {args.tier})."
    role = f"pentrain_{args.quest_id.replace('-', '_')}" if args.role else ""
    fmt = {"quest_id": args.quest_id, "track": args.track, "tier": args.tier,
           "title": title, "tagline": tagline, "role": role}

    qdir.mkdir(parents=True)
    (qdir / "quest.yaml").write_text(QUEST_YAML.format(**fmt))
    (qdir / "briefing.md").write_text(BRIEFING_MD.format(**fmt))
    (qdir / "defense.md").write_text(DEFENSE_MD.format(**fmt))
    (qdir / "coach_context.md").write_text(COACH_CONTEXT_MD.format(**fmt))
    print(f"[+] quest dir: {qdir.relative_to(REPO)}")

    if args.role:
        rdir = REPO / "content" / "ansible-roles" / role
        if rdir.exists():
            print(f"[!] role {role} already exists - skipped")
        else:
            (rdir / "tasks").mkdir(parents=True)
            (rdir / "handlers").mkdir(parents=True)
            (rdir / "tasks" / "main.yml").write_text(ROLE_TASKS.format(**{**fmt, "role": role}))
            (rdir / "handlers" / "main.yml").write_text(ROLE_HANDLERS)
            print(f"[+] role: content/ansible-roles/{role}")

    # immediate schema validation of what we just wrote
    try:
        from app.services.packs import validate_quest_dir
    except ImportError:
        print("[!] backend not importable - skipped validation (pip install -e backend)")
        return 0
    spec, errs = validate_quest_dir(qdir)
    for e in errs:
        print(f"ERR {e}")
    if spec and not errs:
        print(f"[ok] {args.quest_id} validates - fill in the TODOs, then run scripts/lint_packs.py")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
