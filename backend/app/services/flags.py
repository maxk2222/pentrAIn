"""Flag generation, injection and validation.

Dynamic flags: secret = pentrAIn{hmac(app_secret, session.flag_seed + flag_key)[:12]}
→ unique per session attempt (anti-replay across resets). Injected into target
VMs via qemu-guest-agent file writes (file kind) at deploy and after soft reset.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets as _secrets

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..models.domain import ExpectedFlag, Flag, FlagKind, FlagSubmission, Session


def new_seed() -> str:
    return _secrets.token_hex(8)


def new_telemetry_token() -> str:
    return _secrets.token_hex(16)


def derive_flag_secret(flag_seed: str, flag_key: str) -> str:
    cfg = get_config()
    digest = hmac.new(cfg.app_secret.encode(), f"{flag_seed}:{flag_key}".encode(), hashlib.sha256)
    return f"pentrAIn{{{digest.hexdigest()[:16]}}}"


def _flag_vmid(session: Session, vm_name: str | None) -> int | None:
    """Resolve a flag's target VM. "kali" is the trainee console VM itself —
    scripting quests check their artifacts there; everything else maps through
    the deployed target_vmids name→vmid dict."""
    if not vm_name:
        return None
    if vm_name == "kali":
        return session.kali_vmid
    return (session.target_vmids or {}).get(vm_name)


async def create_expected_flags(db: AsyncSession, session: Session, flags: list[Flag]) -> None:
    """(Re)generate per-session secrets for every quest flag.

    Replace semantics: soft reset rotates flag_seed, so stale secrets from a
    previous deploy must not stay valid."""
    await db.execute(delete(ExpectedFlag).where(ExpectedFlag.session_id == session.id))
    for f in flags:
        db.add(ExpectedFlag(
            session_id=session.id, flag_key=f.key,
            secret=derive_flag_secret(session.flag_seed, f.key)))
    await db.commit()


async def inject_flags(db: AsyncSession, engine, session: Session, flags: list[Flag]) -> list[str]:
    """Write per-session flag files into target VMs via guest agent. Returns log lines."""
    logs: list[str] = []
    expected = {
        r.flag_key: r.secret
        for r in (await db.execute(
            select(ExpectedFlag).where(ExpectedFlag.session_id == session.id))).scalars().all()
    }
    for f in flags:
        if f.kind != FlagKind.FILE.value:
            continue
        spec = f.command_spec or {}
        vm_name = spec.get("vm")
        path = spec.get("file_path") or f"/root/{f.key}.txt"
        vmid = _flag_vmid(session, vm_name)
        if not vmid:
            logs.append(f"flag {f.key}: no vmid for vm={vm_name} — skipped")
            continue
        secret = expected.get(f.key)
        if not secret:
            continue
        try:
            container = spec.get("container")
            if container:
                # docker exec needs a shell inside the image — distroless
                # containers (juice-shop) have none, and agent_exec_sh doesn't
                # raise on non-zero exits so failures used to log as
                # "injected". Stage on the host and docker-cp instead.
                tmp = f"/tmp/.pentrain-flag-{f.key}"
                await engine.pve.agent_file_write(vmid, tmp, f"{secret}\n")
                res = await engine.pve.agent_exec_sh(
                    vmid,
                    f"docker cp {_shq(tmp)} {_shq(container)}:{_shq(path)} "
                    f"&& rm -f {_shq(tmp)}")
                if res.get("exitcode") != 0:
                    raise RuntimeError(
                        f"docker cp rc={res.get('exitcode')}: "
                        f"{res.get('err') or res.get('out')}")
            elif path.startswith("/"):
                await engine.pve.agent_write_file(vmid, path, f"{secret}\n")
            else:
                # windows path (C:\...) — guest-file-write needs no guest
                # shell and survives where exec-args wedge the virtio channel;
                # the role owns the parent directory
                await engine.pve.agent_file_write(vmid, path, f"{secret}\n")
            logs.append(f"flag {f.key} injected → {vm_name}:{path}"
                        + (f" (container {container})" if container else ""))
        except Exception as e:
            logs.append(f"flag {f.key} inject FAILED ({vm_name}): {e}")
    return logs


async def submit_flag(db: AsyncSession, engine, session: Session, value: str) -> dict:
    """Validate a submitted flag value. Returns {correct, flag_key, points, all_solved}."""
    expected = {
        r.flag_key: r.secret
        for r in (await db.execute(
            select(ExpectedFlag).where(ExpectedFlag.session_id == session.id))).scalars().all()
    }
    matched = next((k for k, s in expected.items() if s == value.strip()), None)
    correct = matched is not None
    db.add(FlagSubmission(session_id=session.id, flag_key=matched or "?", value=value[:256], correct=correct))
    await db.commit()

    flags = (await db.execute(select(Flag).where(Flag.quest_id == session.quest_id))).scalars().all()
    solved_keys = {
        r.flag_key for r in (await db.execute(
            select(FlagSubmission).where(
                FlagSubmission.session_id == session.id, FlagSubmission.correct.is_(True)))
        ).scalars().all()
    }
    all_solved = bool(flags) and all(f.key in solved_keys for f in flags)
    points = next((f.points for f in flags if f.key == matched), 0)
    return {"correct": correct, "flag_key": matched, "points": points, "all_solved": all_solved,
            "solved": sorted(solved_keys), "total": len(flags)}


async def check_command_flag(db: AsyncSession, engine, session: Session, flag: Flag) -> bool | None:
    """kind=command: run spec on the target VM (optionally inside a container),
    compare output to `expect` (substring) or exitcode. Returns None when the
    checker itself could not run (guest agent down/unreachable) — a None must
    surface as 'unreachable', not as a wrong-answer False."""
    spec = flag.command_spec or {}
    vmid = _flag_vmid(session, spec.get("vm", ""))
    cmd = spec.get("cmd")
    if not vmid or not cmd:
        return False
    if spec.get("container"):
        cmd = f"docker exec {spec['container']} /bin/sh -c {_shq(cmd)}"
    try:
        res = await engine.pve.agent_exec_sh(vmid, cmd)
    except Exception:
        return None
    expect = spec.get("expect")
    if expect is None:
        return res.get("exitcode") == 0
    return str(expect).strip() in (res.get("out") or "")


async def check_and_record_flag(db: AsyncSession, engine, session: Session, flag_key: str) -> dict:
    """Verify a command/state flag on the target and record a correct submission."""
    flag = (await db.execute(
        select(Flag).where(Flag.quest_id == session.quest_id, Flag.key == flag_key))
    ).scalar_one_or_none()
    if not flag or flag.kind != FlagKind.COMMAND.value:
        return {"correct": False, "flag_key": flag_key, "points": 0,
                "all_solved": False, "solved": [], "total": 0,
                "error": "not a command flag"}
    ok = await check_command_flag(db, engine, session, flag)
    if ok is None:
        return {"correct": False, "flag_key": flag_key, "points": 0,
                "all_solved": False, "solved": [], "total": 0,
                "error": "checker unreachable (target guest agent down) — your state is "
                         "probably fine; retry check_flag in ~60s"}
    detail = None
    if not ok:
        detail = await _command_flag_detail(engine, session, flag)
        # where the check ran — hostnames are visible via range DNS anyway,
        # and "the grader reads pcap01's fs, not kali's" is the exact fact
        # a vanished-write loop needs (s11: report written 5x on kali).
        vm = (flag.command_spec or {}).get("vm")
        if vm and vm != "kali":
            loc = f"check ran on {vm}"
            detail = f"{detail} — {loc}" if detail else loc
    if ok:
        expected = (await db.execute(
            select(ExpectedFlag).where(
                ExpectedFlag.session_id == session.id,
                ExpectedFlag.flag_key == flag_key))).scalar_one_or_none()
        db.add(FlagSubmission(session_id=session.id, flag_key=flag_key,
                              value=expected.secret if expected else "checked",
                              correct=True))
        await db.commit()
    flags = (await db.execute(select(Flag).where(Flag.quest_id == session.quest_id))).scalars().all()
    solved_keys = {
        r.flag_key for r in (await db.execute(
            select(FlagSubmission).where(
                FlagSubmission.session_id == session.id,
                FlagSubmission.correct.is_(True)))).scalars().all()}
    all_solved = bool(flags) and all(f.key in solved_keys for f in flags)
    res = {"correct": ok, "flag_key": flag_key if ok else None,
           "points": flag.points if ok else 0, "all_solved": all_solved,
           "solved": sorted(solved_keys), "total": len(flags)}
    if detail:
        res["detail"] = detail
    return res


async def _command_flag_detail(engine, session: Session, flag: Flag) -> str | None:
    """Failure diagnostics for compound `a && b && c` checks: run each
    segment alone and report WHICH failed — 'condition 2 of 3' focuses the
    trainee without leaking expected values (s54: the agent burned ~40min
    on 'correct:false' with no idea which grep missed)."""
    spec = flag.command_spec or {}
    cmd = spec.get("cmd") or ""
    vmid = _flag_vmid(session, spec.get("vm", ""))
    if not vmid or " && " not in cmd or spec.get("expect") is not None:
        return None
    parts = [p.strip() for p in cmd.split(" && ") if p.strip()]
    if len(parts) < 2:
        return None
    if spec.get("container"):
        parts = [f"docker exec {spec['container']} /bin/sh -c {_shq(p)}"
                 for p in parts]
    failed = []
    for i, part in enumerate(parts):
        try:
            res = await engine.pve.agent_exec_sh(vmid, part)
            if res.get("exitcode") != 0:
                failed.append(i + 1)
        except Exception:
            failed.append(i + 1)
    if not failed:
        return None
    if len(failed) == len(parts):
        # all failed — the FIRST condition is the root cause (e.g. test -f
        # when the file simply isn't there). Naming it still points the
        # trainee at the real gap instead of "check failed" silence.
        return f"condition 1 of {len(parts)} failed (all conditions failed)"
    nums = ",".join(str(n) for n in failed)
    return f"condition {nums} of {len(parts)} failed"


def _shq(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"
