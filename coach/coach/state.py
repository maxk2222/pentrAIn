"""Session working memory: what the coach knows about a trainee's run."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field


@dataclass
class CommandRec:
    ts: float
    command: str
    cwd: str = ""
    exit_code: int | None = None
    from_coach: bool = False  # issued via exec_in_kali — must not count as trainee activity


@dataclass
class SessionState:
    session_id: int
    commands: list[CommandRec] = field(default_factory=list)
    checkpoints_hit: set[str] = field(default_factory=set)
    flags_solved: set[str] = field(default_factory=set)
    last_progress_ts: float = field(default_factory=time.time)   # last checkpoint/flag/milestone
    last_activity_ts: float = field(default_factory=time.time)   # last command
    last_nudge_ts: float = 0.0
    last_hint_ts: float = 0.0
    nudges_sent: int = 0
    exec_count: int = 0
    # proactive turns in a row without trainee progress — drives backoff
    proactive_streak: int = 0
    # buffered user chat lines awaiting a debounced answer
    pending_chat: list[str] = field(default_factory=list)
    # last user message — rendered as OPERATOR_DIRECTIVE on L4 so takeover
    # turns can't dismiss it as trainee chatter (they ignored it otherwise)
    operator_directive: str = ""
    operator_directive_ts: float = 0.0
    # latest screenshot description produced by the vision model
    screen_desc: str = ""
    notes: list[str] = field(default_factory=list)               # coach-side observations
    autonomy_level: int = 2
    coach_enabled: bool = True
    subagents_enabled: bool = False   # L4 parallel worker panes allowed
    state: str = "ready"

    def add_command(self, ts: float, command: str, cwd: str = "", exit_code=None,
                    from_coach: bool = False) -> None:
        self.commands.append(CommandRec(ts, command, cwd, exit_code, from_coach))
        # coach-issued commands must NOT masquerade as trainee activity —
        # otherwise idle detection dies while the coach is driving
        if not from_coach:
            self.last_activity_ts = ts
        if len(self.commands) > 400:
            self.commands = self.commands[-400:]

    def mark_exit(self, code: int) -> None:
        """Attach a command_result event to the most recent command — only if it
        just ran (a stray precmd elsewhere must not mislabel old entries)."""
        last = self.commands[-1] if self.commands else None
        if last and last.exit_code is None and time.time() - last.ts < 60:
            last.exit_code = code

    def progress(self, ts: float | None = None) -> None:
        self.last_progress_ts = ts or time.time()
        self.proactive_streak = 0  # real progress resets the escalation backoff

    def stuck_s(self, now: float | None = None) -> float:
        # progress clock only runs once seeded on attach — before that
        # "stuck" is undefined, not 56 years
        if self.last_progress_ts <= 0:
            return 0.0
        return (now or time.time()) - self.last_progress_ts

    def idle_s(self, now: float | None = None) -> float:
        # no trainee activity observed yet → "just started", not idle-forever
        if self.last_activity_ts <= 0:
            return 0.0
        return (now or time.time()) - self.last_activity_ts

    def recent_commands(self, n: int = 25) -> list[str]:
        return [c.command for c in self.commands[-n:]]

    def recent_formatted(self, n: int = 25) -> list[str]:
        """Commands annotated with their exit status — how the LLM sees them."""
        out = []
        for c in self.commands[-n:]:
            line = c.command
            if c.from_coach:
                line = f"[coach-ran] {line}"
            elif c.cwd:
                line = f"[{c.cwd}] {line}"
            if c.exit_code is not None:
                line += f"  # exit {c.exit_code}"
            out.append(line)
        return out

    def tool_diversity(self) -> set[str]:
        return {c.command.split()[0] for c in self.commands if c.command.split()}

    def done_commands(self, n: int = 10) -> list[str]:
        """Coach commands that already succeeded — shown in context so the
        model stops re-verifying established facts (a real failure mode)."""
        out: list[str] = []
        for c in self.commands:
            if c.from_coach and c.exit_code == 0 and c.command not in out:
                out.append(c.command)
        return out[-n:]

    # bare `> target` is a write; fd-number redirects (`2>`) aren't, and a
    # target of /dev/null is a discard — not a file worth guarding
    _WRITE_RE = re.compile(r"(?<!\d)>\s*(/(?!dev/null\b)\S+)"
                           r"|\btee\s+(-a\s+)?(\S+)")
    _RECON_RE = re.compile(
        r"\b(nmap|masscan|rustscan|unicornscan|naabu|zmap|nikto|gobuster|"
        r"feroxbuster|dirb|dirsearch|ffuf|nuclei)\b")
    _IP_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")

    def recon_counts(self) -> dict[str, int]:
        """Scan/enumeration commands per target — the model re-scans variants
        forever otherwise (nmap -sV, then -sT, then -O, then -p-…). Used to
        saturate the context with a 'recon is done, act' directive."""
        counts: dict[str, int] = {}
        for c in self.commands:
            if not c.from_coach or not self._RECON_RE.search(c.command):
                continue
            ips = self._IP_RE.findall(c.command)
            if ips:
                tgt = ips[-1]
            else:
                toks = c.command.split()
                tgt = toks[-1] if toks else "?"
            counts[tgt] = counts.get(tgt, 0) + 1
        return counts

    def written_files(self) -> list[str]:
        """Files created via redirects or tee (cat > f, tee f, printf > f).
        The heredoc CONTENT differs every write, so exact-command dedup
        never fires — the model rewrites the same solver forever. Listed
        in context so 'written' is a settled fact."""
        out: list[str] = []
        for c in self.commands:
            if c.exit_code != 0:
                continue
            m = self._WRITE_RE.search(c.command)
            if not m:
                continue
            path = m.group(1) or m.group(3)
            if path and path != "/dev/null" and path not in out:
                out.append(path)
        return out


class CheckpointMatcher:
    """Matches quest checkpoint regexes against the live command stream."""

    def __init__(self, checkpoints: list[dict], target_hint: str = ""):
        self._rules: list[tuple[str, str, re.Pattern]] = []
        for cp in checkpoints:
            det = cp.get("detect", {}) or {}
            pat = det.get("command_match")
            if pat:
                # quests embed {target_net} as a placeholder for the range subnet
                pat = pat.replace("{target_net}", r"10\.\d+\.\d+\.\d+")
                try:
                    self._rules.append((cp["id"], cp.get("name", cp["id"]), re.compile(pat)))
                except re.error:
                    continue
        self._target_hint = target_hint

    def check(self, command: str) -> list[str]:
        """Return checkpoint ids this command triggers."""
        return [cid for cid, _name, pat in self._rules if pat.search(command)]

    def name_for(self, cid: str) -> str:
        return next((name for c, name, _ in self._rules if c == cid), cid)
