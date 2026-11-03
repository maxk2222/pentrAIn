"""Trajectory log — one JSONL line per LLM sub-turn, one file per session.

Research basis: post-hoc eval + future SFT/PRM data need the *turn-level*
record (trigger → actions → results → facts), not just chat messages.
The DB already audits effects (CoachAction rows); this log adds the
decision context around them — reason, chain position, denial, tokens.

Bounded by design: every string field is head-truncated so a runaway
session can't fill the disk. Disabled via PENTRAIN_TRAJ_DIR="" — the
coach still runs identical turns, just without the file.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path


class TrajLog:
    """Append-only JSONL writer. `None`-safe: for_session returns a
    NullTrajLog (same interface, writes nothing) when disabled."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8", buffering=1)  # line-buffered

    def record(self, **kw) -> None:
        kw.setdefault("ts", round(time.time(), 2))
        with contextlib.suppress(Exception):  # logging must never break a turn
            line = json.dumps(kw, ensure_ascii=False, default=str)
            if len(line) > 12000:
                # oversized record (huge action list) — shrink, keep it valid:
                # drop middle actions, keep head+tail, never slice mid-JSON
                acts = kw.get("actions")
                if isinstance(acts, list) and len(acts) > 8:
                    kw["actions"] = acts[:4] + [{"t": "…", "arg": "",
                                                "res": f"{len(acts) - 6} "
                                                "actions elided",
                                                "denied": False}] + acts[-2:]
                    line = json.dumps(kw, ensure_ascii=False, default=str)
                if len(line) > 16000:
                    line = json.dumps({"kind": "oversized",
                                       "bytes": len(line),
                                       "ts": kw.get("ts")})
            self._fh.write(line + "\n")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._fh.close()


class NullTrajLog:
    path = None

    def record(self, **kw) -> None:
        pass

    def close(self) -> None:
        pass


def for_session(session_id: int) -> TrajLog | NullTrajLog:
    d = os.environ.get("PENTRAIN_TRAJ_DIR", "./traj")
    if not d:
        return NullTrajLog()
    try:
        return TrajLog(Path(d) / f"session-{session_id}.jsonl")
    except Exception:
        return NullTrajLog()


def rotate(session_id: int) -> None:
    """Soft-reset boundary: rename session-{sid}.jsonl aside so the new
    attempt starts a clean file. The old run's record survives for post-hoc
    eval — the file's whole purpose — but the observer's fresh scan must not
    re-consume pre-reset evidence (s84: stale advisory fired on a clean run
    because the tailer rebuilt counters from the dead attempt's turns)."""
    d = os.environ.get("PENTRAIN_TRAJ_DIR", "./traj")
    if not d:
        return
    p = Path(d) / f"session-{session_id}.jsonl"
    with contextlib.suppress(OSError):
        p.rename(p.with_name(f"{p.stem}.{int(time.time())}.jsonl"))
