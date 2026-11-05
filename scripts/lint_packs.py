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
    """telemetry-agent/ is canonical; the kali + target roles ship embedded
    copies. Drift here silently breaks telemetry on deployed ranges — fail
    loudly."""
    src_dir = REPO / "telemetry-agent"
    role_dirs = {
        "kali-agent": REPO / "content/ansible-roles/pentrain_kali_agent/files",
        "target-agent": REPO / "content/ansible-roles/pentrain_target_agent/files",
    }
    errors: list[str] = []
    for label, role_dir in role_dirs.items():
        for f in src_dir.iterdir():
            if f.is_file():
                dst = role_dir / f.name
                if not dst.exists():
                    errors.append(f"{label} role missing {f.name}")
                elif dst.read_bytes() != f.read_bytes():
                    errors.append(f"{label} role {f.name} out of sync with telemetry-agent/")
    return errors


def check_roles(found) -> list[str]:
    """Every role a quest references must exist under content/ansible-roles —
    a typo'd name would only fail at deploy time on a live range."""
    roles_root = REPO / "content" / "ansible-roles"
    errors: list[str] = []
    for qdir, spec in found:
        role_owners = [("kali", spec.topology.kali.roles)]
        role_owners.extend((v.name, v.roles) for v in spec.topology.vms)
        for vm_name, roles in role_owners:
            for r in roles:
                name = r["name"] if isinstance(r, dict) else r
                if not isinstance(name, str):
                    continue
                if not (roles_root / name / "tasks" / "main.yml").exists():
                    errors.append(f"{qdir.name}: role {name!r} on vm {vm_name} "
                                  "missing content/ansible-roles/" + name)
    return errors


def check_role_tasks() -> list[str]:
    """Structural role checks that only fail at deploy time otherwise:
    - copy destinations must not precede the `file: state=directory` that
      creates their parent
    - every `notify:` must have a matching handler
    - roles creating password-login users must enable PasswordAuthentication
    - meta/main.yml — Ludus refuses role registration without galaxy_info
    """
    import yaml as _yaml

    errors: list[str] = []
    roles_root = REPO / "content" / "ansible-roles"
    for rdir in sorted(roles_root.iterdir()):
        tasks = rdir / "tasks" / "main.yml"
        if not tasks.exists():
            continue
        if rdir.name.startswith("_") is False and not (rdir / "meta" / "main.yml").exists():
            errors.append(f"{rdir.name}: missing meta/main.yml — "
                          "ludus role registration refuses it")
        text = tasks.read_text()
        try:
            task_list = _yaml.safe_load(text) or []
        except _yaml.YAMLError as e:
            errors.append(f"{rdir.name}: tasks/main.yml does not parse: {e}")
            continue
        if not isinstance(task_list, list):
            continue

        # -- collect state=directory paths in order + copy dests in order
        dirs_at: dict[str, int] = {}
        copies: list[tuple[str, int]] = []
        creates_user = False
        notified: set[str] = set()
        for i, t in enumerate(task_list):
            if not isinstance(t, dict):
                continue
            included = (t.get("include_role") or t.get("ansible.builtin.include_role")
                        or t.get("import_role") or t.get("ansible.builtin.import_role") or {})
            included_name = included.get("name") if isinstance(included, dict) else None
            if included_name and not (
                roles_root / str(included_name) / "tasks" / "main.yml"
            ).exists():
                errors.append(
                    f"{rdir.name}: included role {included_name!r} "
                    "missing content/ansible-roles/" + str(included_name))
            fmod = t.get("file") or t.get("ansible.builtin.file") or {}
            if isinstance(fmod, dict) and fmod.get("state") == "directory":
                dirs_at.setdefault(str(fmod.get("path", "")), i)
            cmod = t.get("copy") or t.get("ansible.builtin.copy") or {}
            if isinstance(cmod, dict) and cmod.get("dest"):
                copies.append((str(cmod["dest"]), i))
            umod = t.get("user") or t.get("ansible.builtin.user") or {}
            if isinstance(umod, dict) and umod.get("password"):
                creates_user = True
            n = t.get("notify")
            if isinstance(n, str):
                notified.add(n)
            elif isinstance(n, list):
                notified.update(str(x) for x in n)

        for dest, idx in copies:
            for d, didx in dirs_at.items():
                if d and d != "/" and dest.startswith(d.rstrip("/") + "/") and didx > idx:
                    errors.append(
                        f"{rdir.name}: copy to {dest} (task #{idx}) precedes "
                        f"directory {d} (task #{didx})")

        # -- notify ↔ handler
        hfile = rdir / "handlers" / "main.yml"
        handlers: set[str] = set()
        if hfile.exists():
            for h in (_yaml.safe_load(hfile.read_text()) or []):
                if isinstance(h, dict) and h.get("name"):
                    handlers.add(str(h["name"]))
        for n in sorted(notified):
            if n not in handlers:
                errors.append(f"{rdir.name}: notify {n!r} has no handler")

        # -- password-login users need sshd password auth *somewhere in the
        #    role set*. Role-level findings are collected here; the quest
        #    pass below decides error vs warning (a sibling role — e.g.
        #    pentrain_wifi_lab — may own sshd config for the whole lab).
        if creates_user and "PasswordAuthentication yes" not in text:
            _USER_AUTH_FINDINGS.append(rdir.name)
    return errors


_USER_AUTH_FINDINGS: list[str] = []


def check_ssh_auth(found) -> tuple[list[str], list[str]]:
    """Quest-level sshd consistency: for every VM, if a role installs or
    configures openssh-server, SOME role on that VM must set
    PasswordAuthentication yes — otherwise password login users are
    unreachable. Password users with no sshd config at all → warning."""
    import yaml as _yaml

    errors: list[str] = []
    warnings: list[str] = []
    roles_root = REPO / "content" / "ansible-roles"
    for qdir, spec in found:
        for v in spec.topology.vms:
            installs_sshd = False
            sets_passauth = False
            for r in v.roles:
                name = r["name"] if isinstance(r, dict) else r
                t = roles_root / str(name) / "tasks" / "main.yml"
                if not t.exists():
                    continue
                try:
                    tasks = _yaml.safe_load(t.read_text()) or []
                except _yaml.YAMLError:
                    continue
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    apt = task.get("apt") or task.get("ansible.builtin.apt") or {}
                    names = apt.get("name") if isinstance(apt, dict) else None
                    if names and ("openssh-server" in
                                  (names if isinstance(names, list) else [names])):
                        installs_sshd = True
                    copy_or_line = task.get("copy") or task.get("lineinfile") or {}
                    dest = (copy_or_line.get("dest") or copy_or_line.get("path") or ""
                            if isinstance(copy_or_line, dict) else "")
                    if "sshd" in str(dest):
                        installs_sshd = True
                if "PasswordAuthentication yes" in t.read_text():
                    sets_passauth = True
            if installs_sshd and not sets_passauth:
                errors.append(
                    f"{qdir.name}: vm {v.name} configures/installs sshd but no "
                    "attached role sets PasswordAuthentication yes")
    for role in _USER_AUTH_FINDINGS:
        warnings.append(
            f"{role}: password-login user without PasswordAuthentication in "
            "the same role (ok if a sibling role owns sshd)")
    return errors, warnings


# Audit evidence files must be raw artifacts (manifests, logs, code,
# configs). Assessment sections hand the learner the finished answer —
# `cat` + paraphrase would solve the quest. Findings belong in the
# learner's report; instructions belong in briefing/coach context.
AUDIT_FORBIDDEN = (
    "expected controls", "required outcome", "review task",
    "expected findings", "recommended controls", "finding:",
    "remediation required", "acceptance criteria",
)


def check_audit_fixtures() -> list[str]:
    errors: list[str] = []
    root = REPO / "content" / "ansible-roles" / "pentrain_audit_fixtures" / "files"
    if not root.exists():
        return errors
    for f in sorted(root.rglob("*.md")):
        low = f.read_text().lower()
        for pat in AUDIT_FORBIDDEN:
            if pat in low:
                errors.append(f"{f.relative_to(root)}: evidence file contains "
                              f"answer-bearing section {pat!r}")
    return errors


DRAFT_PATTERNS = ("verify before", "signoff", "wait —", "wait --", "TODO",
                  "FIXME", "XXX", "draft")


def check_draft_notes(found) -> list[str]:
    errors: list[str] = []
    for qdir, _spec in found:
        for fname in ("coach_context.md", "briefing.md"):
            f = qdir / fname
            if not f.exists():
                continue
            low = f.read_text().lower()
            for pat in DRAFT_PATTERNS:
                if pat.lower() in low:
                    errors.append(f"{qdir.name}: {fname} contains draft note {pat!r}")
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
    errors = (errors + check_roles(found) + check_role_tasks()
              + check_draft_notes(found) + check_audit_fixtures())
    ssh_errs, ssh_warns = check_ssh_auth(found)
    errors += ssh_errs
    warnings = check_cheatsheets(found) + ssh_warns
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
