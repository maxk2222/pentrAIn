#!/usr/bin/env python3
"""Lint pentrAIn quest packs — validates every quest dir against the loader schema.

Usage: python scripts/lint_packs.py [content/packs]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.packs import discover_quests

REPO = Path(__file__).resolve().parent.parent


def check_agent_sync() -> list[str]:
    """telemetry-agent/ is canonical; the kali role ships embedded copies.
    Drift here silently breaks telemetry on deployed ranges — fail loudly."""
    src_dir = REPO / "telemetry-agent"
    role_dir = REPO / "content/ansible-roles/pentrain_kali_agent/files"
    errors: list[str] = []
    for f in src_dir.iterdir():
        if f.is_file():
            dst = role_dir / f.name
            if not dst.exists():
                errors.append(f"kali-agent role missing {f.name}")
            elif dst.read_bytes() != f.read_bytes():
                errors.append(f"kali-agent role {f.name} out of sync with telemetry-agent/")
    return errors


def check_roles(found) -> list[str]:
    """Every role a quest references must exist under content/ansible-roles —
    a typo'd name would only fail at deploy time on a live range."""
    roles_root = REPO / "content" / "ansible-roles"
    errors: list[str] = []
    for qdir, spec in found:
        for v in spec.topology.vms:
            for r in v.roles:
                name = r["name"] if isinstance(r, dict) else r
                if not isinstance(name, str):
                    continue
                if not (roles_root / name / "tasks" / "main.yml").exists():
                    errors.append(f"{qdir.name}: role {name!r} on vm {v.name} "
                                  "missing content/ansible-roles/" + name)
    return errors


def check_cheatsheets(found) -> list[str]:
    """cheatsheet.md is optional — warn, never fail. Tracks get the same
    courtesy: content/packs/<track>/cheatsheet.md feeds the sheet panel."""
    warnings: list[str] = []
    seen_tracks: set[str] = set()
    for qdir, _spec in found:
        if not (qdir / "cheatsheet.md").exists():
            warnings.append(f"{qdir.name}: no cheatsheet.md (optional)")
        seen_tracks.add(qdir.parent)
    for tdir in sorted(seen_tracks):
        if not (tdir / "cheatsheet.md").exists():
            warnings.append(f"track {tdir.name}: no track-level cheatsheet.md (optional)")
    return warnings


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "content/packs")
    found, errors = discover_quests(root)
    errors = errors + check_roles(found)
    warnings = check_cheatsheets(found)
    for _qdir, spec in found:
        flags = len(spec.flags)
        vms = len(spec.topology.vms) + 1  # +kali
        print(f"OK  {spec.meta.id:32s} tier={spec.meta.tier} track={spec.meta.track:18s} "
              f"vms={vms} flags={flags} hints={len(spec.hints)}")
    for w in warnings:
        print(f"WARN {w}")
    for e in errors + check_agent_sync():
        print(f"ERR {e}")
    total = len(errors) + len(check_agent_sync())
    # role-existence errors were folded into `errors` already
    print(f"\n{len(found)} quest(s), {total} error(s), {len(warnings)} warning(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
