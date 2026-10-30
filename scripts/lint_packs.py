#!/usr/bin/env python3
"""Lint PenTrAIn quest packs — validates every quest dir against the loader schema.

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


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "content/packs")
    found, errors = discover_quests(root)
    for qdir, spec in found:
        flags = len(spec.flags)
        vms = len(spec.topology.vms) + 1  # +kali
        print(f"OK  {spec.meta.id:32s} tier={spec.meta.tier} track={spec.meta.track:18s} "
              f"vms={vms} flags={flags} hints={len(spec.hints)}")
    for e in errors + check_agent_sync():
        print(f"ERR {e}")
    total = len(errors) + len(check_agent_sync())
    print(f"\n{len(found)} quest(s), {total} error(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
