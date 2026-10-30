#!/usr/bin/env python3
"""pentrain-telemetried — Kali-side telemetry shipper (stdlib only).

Reads /etc/pentrain/telemetried.conf (TOKEN=, SESSION=, API=), tails
/var/log/pentrain/*.log produced by the shell hook, batches events and
POSTs them to the pentrAIn backend /api/telemetry. Spools to disk when the
backend is unreachable (e.g. Ludus testing mode), retries forever.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.request
from pathlib import Path

CONF = Path("/etc/pentrain/telemetried.conf")
LOGDIR = Path("/var/log/pentrain")
SPOOL = Path("/var/spool/pentrain/buffer.jsonl")
BATCH_MAX = 50
FLUSH_S = 3.0
HEARTBEAT_S = 60


def load_conf() -> dict[str, str]:
    out: dict[str, str] = {}
    if CONF.exists():
        for line in CONF.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


class Tailer:
    """Tails all files in LOGDIR, remembering offsets across restarts."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.offsets: dict[str, int] = {}
        try:
            self.offsets = json.loads(state_file.read_text())
        except Exception:
            pass

    def save(self) -> None:
        try:
            self.state_file.write_text(json.dumps(self.offsets))
        except Exception:
            pass

    def read_new(self) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        for path in sorted(LOGDIR.glob("*.log")):
            key = str(path)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            off = self.offsets.get(key)
            if off is None:
                off = 0  # new file → ship the whole file (first commands matter)
            elif off > size:
                off = 0  # rotated/truncated → start over
            try:
                with path.open("r", errors="replace") as f:
                    f.seek(off)
                    for line in f:
                        line = line.rstrip("\n")
                        if line.strip():
                            lines.append((key, line))
                    self.offsets[key] = f.tell()
            except OSError:
                continue
        return lines


def parse_hook_line(path: str, line: str) -> dict | None:
    """hook line formats:
    command: <epoch>\t<user>\t<cwd>\t<command>
    result:  R\t<exit_code>   (written by PROMPT_COMMAND/precmd after each command)
    """
    if line.startswith("R\t"):
        try:
            return {"kind": "command_result",
                    "payload": {"exit_code": int(line.split("\t", 1)[1].strip())}}
        except ValueError:
            return None
    parts = line.split("\t")
    if len(parts) < 4:
        return None
    try:
        ts = int(float(parts[0]))
    except ValueError:
        ts = int(time.time())
    # backend/coach contract: payload.command (NOT "cmd")
    return {"kind": "command",
            "payload": {"ts": ts, "user": parts[1], "cwd": parts[2],
                        "command": "\t".join(parts[3:])[:4000]}}


def post(api: str, token: str, events: list[dict]) -> bool:
    body = json.dumps({"token": token, "events": events}).encode()
    req = urllib.request.Request(
        api.rstrip("/") + "/api/telemetry", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def main() -> None:
    hostname = socket.gethostname()
    tailer = Tailer(SPOOL.with_suffix(".offsets.json"))
    pending: list[dict] = []
    # reload spool from a previous run
    if SPOOL.exists():
        for line in SPOOL.read_text().splitlines():
            try:
                pending.append(json.loads(line))
            except Exception:
                pass
        SPOOL.unlink(missing_ok=True)

    last_flush = 0.0
    last_heartbeat = 0.0
    while True:
        conf = load_conf()
        token, api = conf.get("TOKEN", ""), conf.get("API", "")
        now = time.time()

        if token:
            for path, line in tailer.read_new():
                ev = parse_hook_line(path, line)
                if ev:
                    pending.append(ev)
            if now - last_heartbeat >= HEARTBEAT_S:
                pending.append({"kind": "heartbeat",
                                "payload": {"host": hostname, "ts": int(now)}})
                last_heartbeat = now
            tailer.save()

        if pending and (now - last_flush >= FLUSH_S or len(pending) >= BATCH_MAX):
            if not token or not api:
                pass  # not configured yet — keep spooling
            else:
                batch, pending = pending[:BATCH_MAX], pending[BATCH_MAX:]
                if post(api, token, batch):
                    last_flush = now
                else:
                    pending = batch + pending
                    # spool overflow protection
                    if len(pending) > 5000:
                        pending = pending[-5000:]
                    try:
                        SPOOL.parent.mkdir(parents=True, exist_ok=True)
                        SPOOL.write_text("\n".join(json.dumps(e) for e in pending) + "\n")
                    except Exception:
                        pass
        time.sleep(1.0)


if __name__ == "__main__":
    main()
