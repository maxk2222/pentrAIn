"""pentrAIn installer UI — live status board, stdout callback plugin.

Two zones on a TTY:
  log zone     compact, colored, one scrolled line per task/item result
  status bar   bottom 3 lines, redrawn ~7x/s: current stage, running
               task+host, elapsed, ok/changed/skipped/failed counters

Without a TTY (CI, pipes, NO_COLOR, PENTRAIN_UI=plain): the same result
lines are printed plainly — no bar, no cursor tricks.

Result lines go through display.display() so ansible's log_path receives
clean uncolored text; the status bar writes raw ANSI and is ephemeral by
design (never logged).
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import threading
import time

import yaml
from ansible import constants as C
from ansible import context
from ansible.errors import AnsibleError
from ansible.plugins.callback import CallbackBase

OK = "\u2713"       # ✓
CHG = "\u21bb"      # ↻
SKIP = "\u2298"     # ⊘
ERR = "\u2717"      # ✗
WARN = "!"
ARROW = "\u25b8"    # ▸


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


class CallbackModule(CallbackBase):
    CALLBACK_NAME = "pentrain_ui"
    CALLBACK_TYPE = "stdout"
    CALLBACK_VERSION = 2.0

    def __init__(self):
        super().__init__()
        self._tty = (
            sys.stdout.isatty()
            and not os.environ.get("NO_COLOR")
            and not os.environ.get("CI")
            and os.environ.get("PENTRAIN_UI") != "plain"
        )
        self._lock = threading.Lock()
        self._started = time.time()
        self._task_started = self._started
        self._stage_idx = 0
        self._stage_total = self._count_plays()
        self._stage = ""
        self._task = ""
        self._host = ""
        self._counts = {"ok": 0, "changed": 0, "skipped": 0, "failed": 0}
        self._bar_h = 0
        self._stop = threading.Event()
        self._ticker = None
        if self._tty:
            atexit.register(self._restore)
            self._ticker = threading.Thread(target=self._tick, daemon=True)
            self._ticker.start()

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _count_plays() -> int | None:
        try:
            playbooks = (context.CLIARGS.get("playbook")
                         or context.CLIARGS.get("args") or [])
            total = 0
            for pb in playbooks:
                with open(pb) as fh:
                    doc = yaml.safe_load(fh)
                total += len(doc) if isinstance(doc, list) else 1
            return total or None
        except (OSError, yaml.YAMLError, AttributeError, TypeError):
            return None

    def _restore(self) -> None:
        """Always give the cursor back, even on Ctrl-C."""
        if self._tty:
            try:
                sys.stdout.write("\033[?25h")
                sys.stdout.flush()
            except Exception:  # noqa: BLE001,S110 — atexit must never raise
                pass

    # ------------------------------------------------------------------- bar

    def _tick(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                self._redraw_bar()
            self._stop.wait(0.15)

    def _erase_bar(self) -> None:
        if self._bar_h:
            sys.stdout.write(f"\033[{self._bar_h}A\033[0J")
            sys.stdout.flush()
            self._bar_h = 0

    def _redraw_bar(self) -> None:
        if not self._tty or not self._task:
            return
        self._erase_bar()
        width = shutil.get_terminal_size((100, 24)).columns
        total = self._stage_total or "?"
        stage = f"stage {self._stage_idx}/{total} \u00b7 {self._stage}"[:width]
        cur = f"{ARROW} {self._task}"[:width - 32]
        host = f"@{self._host}" if self._host else ""
        running = _fmt_elapsed(time.time() - self._task_started)
        elapsed = f"elapsed {_fmt_elapsed(time.time() - self._started)}"
        ok_s = f"\033[32m{OK} {self._counts['ok']}\033[0m"
        chg_s = f"\033[36m{CHG} {self._counts['changed']}\033[0m"
        skp_s = f"\033[2m{SKIP} {self._counts['skipped']}\033[0m"
        err_s = f"\033[31m{ERR} {self._counts['failed']}\033[0m"
        gap = " " * max(2, width - 30 - len(elapsed))
        lines = [
            f"\033[36m{stage}\033[0m",
            f"{cur}  \033[2m{host}  {running}\033[0m",
            f"{ok_s}  {chg_s}  {skp_s}  {err_s}{gap}\033[2m{elapsed}\033[0m",
        ]
        sys.stdout.write("\033[?25l" + "\n".join(lines) + "\n")
        sys.stdout.flush()
        self._bar_h = len(lines)

    # ----------------------------------------------------------------- lines

    def _line(self, text: str, color: str | None = None) -> None:
        """One scrolled log line: bar out, line in, bar back — under one lock."""
        with self._lock:
            self._erase_bar()
            self._display.display(text, color=color)
            self._redraw_bar()

    def _result_line(self, result, glyph: str, color: str | None) -> None:
        host = result._host.get_name() if result._host else "?"
        name = self._task_name(result)
        self._line(f"  {glyph} {host} \u00b7 {name}", color=color)
        if self._display.verbosity > 0:
            self._line(self._dump_results(result._result) or "")

    def _task_name(self, result=None) -> str:
        try:
            task = result._task if result is not None else None
            return (task.get_name() or "").strip() or "?"
        except (AttributeError, AnsibleError):
            return "?"

    # ------------------------------------------------------------- callbacks

    def v2_playbook_on_play_start(self, play):
        self._stage_idx += 1
        self._stage = (play.get_name() or "").strip()
        total = self._stage_total or "?"
        with self._lock:
            self._erase_bar()
        self._line("")
        self._line(f"\u2500\u2500 stage {self._stage_idx}/{total} \u00b7 {self._stage}", color=C.COLOR_HIGHLIGHT)

    def v2_playbook_on_no_hosts_matched(self):
        self._line(f"  {SKIP} no hosts matched — stage skipped", color="bright black")

    def v2_playbook_on_task_start(self, task, is_conditional):
        name = (task.get_name() or "").strip()
        with self._lock:
            self._task = name
            self._task_started = time.time()
        self._line(f"{ARROW} {name}", color="bright black")

    def v2_runner_on_start(self, host, task):
        with self._lock:
            self._host = host.get_name() if hasattr(host, "get_name") else str(host)

    # ----- per-item events give loops granular lines (template builds etc.)

    def _item_line(self, result, glyph: str, color: str | None) -> None:
        try:
            label = self._get_item_label(result._result)
        except (AttributeError, KeyError, TypeError):
            label = "?"
        self._line(f"    {glyph} {label}", color=color)
        if color == C.COLOR_ERROR:
            msg = result._result.get("stderr") or result._result.get("msg") or ""
            if msg:
                self._line(f"      {msg[:600]}", color=C.COLOR_ERROR)

    def v2_runner_item_on_ok(self, result):
        changed = bool(result._result.get("changed"))
        self._counts["changed" if changed else "ok"] += 1
        self._item_line(result, CHG if changed else OK, "cyan" if changed else C.COLOR_OK)

    def v2_runner_item_on_skipped(self, result):
        self._counts["skipped"] += 1
        self._item_line(result, SKIP, "bright black")

    def v2_runner_item_on_failed(self, result):
        self._counts["failed"] += 1
        self._item_line(result, ERR, C.COLOR_ERROR)

    # ----- task-level events

    def v2_runner_on_ok(self, result):
        if result._result.get("results") is not None:
            return  # loop task — item events already reported per item
        changed = bool(result._result.get("changed"))
        self._counts["changed" if changed else "ok"] += 1
        self._result_line(result, CHG if changed else OK, "cyan" if changed else C.COLOR_OK)

    def v2_runner_on_skipped(self, result):
        if result._result.get("results") is not None:
            return
        self._counts["skipped"] += 1
        self._result_line(result, SKIP, "bright black")

    def _fail(self, result, reason: str) -> None:
        if result._result.get("results") is not None:
            return
        self._counts["failed"] += 1
        host = result._host.get_name() if result._host else "?"
        self._line(f"  {ERR} {host} \u00b7 {self._task_name(result)} — {reason}", color=C.COLOR_ERROR)
        dump = self._dump_results(result._result)
        if dump:
            for line in dump.splitlines():
                self._line(f"      {line}", color=C.COLOR_ERROR)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        if ignore_errors:
            self._line("  ! failed (ignored)", color=C.COLOR_WARN)
            return
        self._fail(result, "failed")

    def v2_runner_on_unreachable(self, result):
        self._fail(result, "unreachable")

    def v2_runner_on_async_failed(self, result):
        self._fail(result, "async failed")

    def v2_runner_retry(self, result):
        retries = result._result.get("retries", "?")
        attempts = result._result.get("attempts", "?")
        self._line(f"  {WARN} retry {attempts}/{retries} — {self._task_name(result)}", color=C.COLOR_WARN)

    # -------------------------------------------------------------- finish

    def v2_playbook_on_stats(self, stats):
        self._stop.set()
        if self._tty:
            with self._lock:
                self._erase_bar()
                sys.stdout.write("\033[?25h")
                sys.stdout.flush()
        self._line("")
        self._line("\u2500\u2500 summary " + "\u2500" * 40, color=C.COLOR_HIGHLIGHT)
        hosts = sorted(stats.processed.keys())
        for host in hosts:
            s = stats.summarize(host)
            color = C.COLOR_ERROR if s.get("failures") or s.get("unreachable") else C.COLOR_OK
            self._line(
                f"  {host:<16} ok={s['ok']:<4} changed={s['changed']:<4} "
                f"unreachable={s['unreachable']:<3} failed={s['failures']}",
                color=color)
        self._line(f"  total {_fmt_elapsed(time.time() - self._started)}")

    def v2_playbook_on_cleanup(self):
        self._stop.set()
        self._restore()
