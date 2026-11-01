#!/usr/bin/env python3
"""pentrain-telemetried — Kali-side telemetry shipper + shell channel.

Reads /etc/pentrain/telemetried.conf (TOKEN=, SESSION=, API=, HOST=, SHELL=),
tails /var/log/pentrain/*.log produced by the shell hook, batches events and
POSTs them to the pentrAIn backend /api/telemetry. Spools to disk when the
backend is unreachable (e.g. Ludus testing mode), retries forever.

When SHELL=1 (kali only — the backend writes the flag into its conf), a
second thread polls /api/terminal/wants/{sid} and opens an OUTBOUND
WebSocket per wanted channel, bridging it to a local PTY running
`tmux new-session -A -s pentrain-web-<chan>` — browser terminal tabs that
survive reconnects. Requires python3-websockets; without it the worker
silently stays off and telemetry is unaffected.
"""
from __future__ import annotations

import contextlib
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
        # HOST names the box in multi-VM telemetry (kali vs targets); falls
        # back to the OS hostname when the backend hasn't written one yet.
        host = conf.get("HOST") or hostname
        now = time.time()

        if token:
            for path, line in tailer.read_new():
                ev = parse_hook_line(path, line)
                if ev:
                    ev["payload"]["host"] = host
                    pending.append(ev)
            if now - last_heartbeat >= HEARTBEAT_S:
                pending.append({"kind": "heartbeat",
                                "payload": {"host": host, "ts": int(now)}})
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


# ---------------- browser shell channel (kali only, SHELL=1) ----------------
#
# The range is inbound-isolated: the backend can't reach kali, but kali can
# reach the API outbound. So instead of an SSH server we poll which terminal
# channels the UI wants and DIAL OUT a websocket per channel, bridged to a
# PTY running tmux. Frame protocol: binary = terminal bytes; text = JSON
# control ({"t":"resize","cols","rows"} in; {"t":"exit","code"} out).

SHELL_POLL_S = 2.0


def _ws_url(api: str, path: str) -> str:
    base = api.rstrip("/")
    base = "ws" + base[base.index("://"):] if "://" in base else "ws://" + base
    return base + path


def _get_json(url: str, timeout: float = 10.0) -> dict | None:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _spawn_pty(chan: str, cols: int, rows: int):
    """Open a PTY, size it, spawn `tmux new -A -s pentrain-web-<chan>` on the
    slave (fresh bash login shell fallback). Returns (master_fd, Popen)."""
    import fcntl
    import os
    import pty
    import struct
    import subprocess
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ,
                struct.pack("HHHH", rows, cols, 0, 0))
    env = {"TERM": "xterm-256color", "HOME": "/root", "PATH": os.environ.get("PATH", ""),
           "SHELL": "/bin/bash", "LANG": os.environ.get("LANG", "C.UTF-8")}
    cmd = (["tmux", "new-session", "-A", "-s", f"pentrain-web-{chan}"]
           if Path("/usr/bin/tmux").exists() else ["bash", "-l"])

    def _preexec() -> None:
        # the child needs the slave as CONTROLLING tty — setsid alone leaves
        # the fallback shell without job control (no fg pgrp → ^C never
        # signals). login_tty = setsid + TIOCSCTTY + dup2 in one (py3.11+).
        if hasattr(os, "login_tty"):
            os.login_tty(slave)
        else:
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave,
                            preexec_fn=_preexec, env=env, close_fds=True)
    os.close(slave)
    os.set_blocking(master, False)
    return master, proc


def _write_all(fd: int, data: bytes) -> bool:
    """os.write may short-write on a big paste — loop until it's all out."""
    import os
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        return True
    except OSError:
        return False


async def _chan_task(api: str, sid: str, token: str, chan: str,
                     cols: int, rows: int, stop) -> None:
    """One channel: ws dial -> pty bridge until either side drops."""
    import asyncio
    import fcntl
    import os
    import struct
    import termios

    import websockets

    url = _ws_url(api, f"/api/terminal/kali/{sid}/{chan}?token={token}")
    master, proc = _spawn_pty(chan, cols, rows)
    loop = asyncio.get_running_loop()
    try:
        async with websockets.connect(url, max_size=None, ping_interval=20) as ws:
            outgoing: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
            paused = False  # backpressure: reader unregisters while full

            def on_readable() -> None:
                nonlocal paused
                try:
                    data = os.read(master, 65536)
                except OSError:
                    data = b""
                if data:
                    try:
                        outgoing.put_nowait(data)
                    except asyncio.QueueFull:
                        # ws can't keep up — stop reading the PTY until the
                        # queue drains instead of dropping terminal bytes
                        paused = True
                        loop.remove_reader(master)
                else:
                    loop.remove_reader(master)
                    with contextlib.suppress(asyncio.QueueFull):
                        outgoing.put_nowait(None)

            loop.add_reader(master, on_readable)

            async def pty_to_ws() -> None:
                nonlocal paused
                while (chunk := await outgoing.get()) is not None:
                    await ws.send(chunk)
                    if paused:
                        paused = False
                        loop.add_reader(master, on_readable)

            async def ws_to_pty() -> None:
                async for msg in ws:
                    if isinstance(msg, bytes):
                        if not _write_all(master, msg):
                            return
                    else:
                        try:
                            ctl = json.loads(msg)
                        except (ValueError, TypeError):
                            continue
                        if ctl.get("t") == "resize":
                            with contextlib.suppress(Exception):
                                fcntl.ioctl(master, termios.TIOCSWINSZ,
                                            struct.pack("HHHH",
                                                        int(ctl["rows"]),
                                                        int(ctl["cols"]), 0, 0))

            async def watch_proc() -> None:
                while proc.poll() is None:
                    await asyncio.sleep(0.5)

            async def watch_stop() -> None:
                await stop.wait()
                await ws.close()

            tasks = {asyncio.ensure_future(f()): n for n, f in
                     (("pty_to_ws", pty_to_ws), ("ws_to_pty", ws_to_pty),
                      ("watch_proc", watch_proc), ("watch_stop", watch_stop))}
            done, pending = await asyncio.wait(
                set(tasks), return_when=asyncio.FIRST_COMPLETED)
            for t_ in done:  # a task exception would otherwise end silently
                if t_.exception() is not None:
                    print(f"[pentrain-shell] chan {chan} task {tasks[t_]} "
                          f"failed: {t_.exception()!r}", flush=True)
            for t_ in pending:
                t_.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t_
            # report exit AFTER the wait — watch_proc may lose the
            # FIRST_COMPLETED race to the pty EOF and get cancelled pre-send
            if proc.poll() is not None:
                with contextlib.suppress(Exception):
                    await ws.send(json.dumps({"t": "exit", "code": proc.returncode}))
    except Exception as e:
        # journalctl -u pentrain-telemetried — first place to look when a tab
        # stays on "waiting for kali agent"
        print(f"[pentrain-shell] chan {chan} ended: {e!r}", flush=True)
    finally:
        with contextlib.suppress(Exception):
            loop.remove_reader(master)
        if proc.poll() is None:
            with contextlib.suppress(Exception):
                proc.terminate()
        with contextlib.suppress(Exception):
            os.close(master)


async def _shell_loop(conf: dict) -> None:
    """Poll wants; keep one _chan_task per wanted channel alive. Re-dials are
    free — tmux -A reattaches to the same server-side session."""
    import asyncio

    sid, token, api = conf.get("SESSION", ""), conf.get("TOKEN", ""), conf.get("API", "")
    if not (sid and token and api):
        return
    running: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}
    while True:
        conf = load_conf()  # token/session rotate on reset — pick up live values
        sid, token = conf.get("SESSION", sid), conf.get("TOKEN", token)
        api = conf.get("API", api)
        # urllib is blocking — off-thread so a slow API never freezes the
        # live channel bridges (input would stall for the whole timeout)
        wants = ((await asyncio.to_thread(
                  _get_json,
                  f"{api.rstrip('/')}/api/terminal/wants/{sid}?token={token}"))
                 or {}).get("chans") or {}
        for chan in list(running):
            task, stop_ev = running[chan]
            if task.done():
                running.pop(chan, None)  # dead chan → may respawn below
            elif chan not in wants:
                stop_ev.set()  # drain: close ws, keep entry until done
        for chan, meta in wants.items():
            if chan not in running:
                stop_ev = asyncio.Event()
                running[chan] = (asyncio.ensure_future(
                    _chan_task(api, sid, token, chan,
                               int(meta.get("cols") or 120),
                               int(meta.get("rows") or 32), stop_ev)), stop_ev)
        await asyncio.sleep(SHELL_POLL_S)


def _start_shell_worker() -> None:
    """Lazy: only when SHELL=1 and python3-websockets is importable. Targets
    never get the flag; missing lib degrades to telemetry-only."""
    import threading

    conf = load_conf()
    if conf.get("SHELL") != "1":
        return
    try:
        import websockets  # noqa: F401
    except ImportError:
        return

    def runner() -> None:
        import asyncio
        asyncio.run(_shell_loop(conf))

    threading.Thread(target=runner, daemon=True, name="pentrain-shell").start()


_start_shell_worker()


if __name__ == "__main__":
    main()
