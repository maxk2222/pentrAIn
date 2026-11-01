"""FactsDB — the coach's externalized working memory (knowledge-graph lite).

Research basis (PEP/VulnBot): agent state must be a compact structured store,
not a growing chat log. Everything here is filled *deterministically* — regex
extraction over command lines and tool output, never an LLM call.

Two observation paths:
  observe_command(cmd)  — telemetry (trainee) commands: ips, creds-in-args,
                          recon markers, pending write/run bookkeeping that
                          mark_run_exit() closes when command_result arrives
  observe_output(cmd, out, code) — coach exec/type results: command-side
                          facts + parsed output facts + confirmed write/run
                          bookkeeping

Consumers: the FACTS: context section, the objective tracker, and the
anti-loop guards (rewrite/rerun/foreign-ip/flag-evidence — consolidated here
so a coach restart rebuilds them from replayed context).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import structlog

from .percept import parse_output, strip_ansi

log = structlog.get_logger(__name__)

IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
FLAG_RE = re.compile(r"pentrAIn\{[^}\s]+\}")
# same semantics as the guards this module replaces (was SessionState._WRITE_RE)
WRITE_RE = re.compile(r"(?<!\d)>\s*(/(?!dev/null\b)\S+)"
                      r"|\btee\s+(-a\s+)?(\S+)")
# interpreter tokens need a real word boundary — \b alone matches the "sh"
# inside "x.sh"; group 2 is the first arg (flags stripped by _run_target)
RUN_RE = re.compile(r"(?:^|[\s|;&(])(python3?|bash|sh|perl|ruby|node)\s+")
RECON_RE = re.compile(
    r"\b(nmap|masscan|rustscan|unicornscan|naabu|zmap|nikto|gobuster|"
    r"feroxbuster|dirb|dirsearch|ffuf|nuclei)\b")

# credential literals typed into commands — a cred the model *uses* counts as
# tested (on the command's target); a cred parsed from output is *found*
_SSHPASS = re.compile(r"\bsshpass\s+-p\s+['\"]?([^\s'\"]{1,80})")
_SMB_U = re.compile(r"-U\s+['\"]?([^\s/%'\"]{1,64})%([^\s'\"]{1,80})")
_MYSQL_U = re.compile(r"\bmysql\b[^\n]*?-u\s*['\"]?([^\s'\"]{1,64})"
                      r"[^\n]*?-p([^\s'\"]{1,80})")
_URL_CRED = re.compile(r"\b(\w[\w.-]{0,47}):([^\s:/@]{2,80})@")
_HYDRA_LP = re.compile(r"\s-l\s+['\"]?([^\s'\"]{1,64})\s+-p\s+['\"]?([^\s'\"]{1,80})")

_SCRIPT_EXT = re.compile(r"\.(py|sh|pl|rb|php|ps1|lua|js|expect)$")
_PENDING_TTL = 60.0     # mirrors SessionState.mark_exit freshness guard


def _kind(path: str) -> str:
    if _SCRIPT_EXT.search(path):
        return "script"
    if re.search(r"loot|flag|creds?|dump|hash|passwd|secret", path, re.IGNORECASE):
        return "loot"
    return "out"


def _run_target(cmd: str) -> str | None:
    """Script path of an interpreter invocation — skips flag args so
    `python3 -u x.py` lands on x.py, not -u (the old regex counted -u)."""
    m = RUN_RE.search(cmd or "")
    if not m:
        return None
    for tok in cmd[m.end():].split():
        if tok == "-c":
            return None      # sh -c 'inline': the inline string isn't a file
        if not tok.startswith("-"):
            return tok
    return None


@dataclass
class HostFact:
    ip: str
    names: set[str] = field(default_factory=set)
    ports: dict[int, str] = field(default_factory=dict)
    scans: int = 0            # recon commands aimed at this host
    note: str = ""            # worker findings land here

    def label(self) -> str:
        name = min(self.names) if self.names else ""
        ports = " ".join(f"{p}:{s.split()[0].split('/')[0]}"
                         for p, s in sorted(self.ports.items()))
        head = f"{name}={self.ip}" if name else self.ip
        return f"{head} [{ports}]" if ports else head


@dataclass
class CredFact:
    user: str
    secret: str
    source: str = ""                      # where found: host, path, cmd
    tested_on: set[str] = field(default_factory=set)   # hosts it was tried on
    valid_on: set[str] = field(default_factory=set)    # hosts it worked on


@dataclass
class FileFact:
    path: str
    kind: str = "out"                     # script | loot | out
    writes: int = 0                       # confirmed writes (exit 0)
    attempts: int = 0                     # write commands seen (telemetry)
    runs: int = 0
    last_exit: int | None = None


@dataclass
class FlagFact:
    seen: int = 0
    submitted: bool = False
    accepted: bool = False


class FactsDB:
    def __init__(self) -> None:
        self.hosts: dict[str, HostFact] = {}
        self.creds: list[CredFact] = []
        self.files: dict[str, FileFact] = {}
        self.flags: dict[str, FlagFact] = {}
        self.ips_seen: set[str] = set()
        self.findings: list[str] = []     # bounded misc evidence (enum users)
        self._pending: tuple[str, str, float] | None = None  # (path, kind, ts)
        self._seen_cmds: set[str] = set()   # dedup: replay + live overlap

    # ---------- command-side extraction ----------

    def add_host(self, ip: str, name: str = "") -> HostFact | None:
        if not ip:
            return None
        h = self.hosts.get(ip)
        if h is None:
            h = self.hosts[ip] = HostFact(ip=ip)
        if name:
            h.names.add(name)
        return h

    def add_cred(self, user: str, secret: str, source: str = "",
                 tested_on: str | None = None,
                 valid_on: str | None = None) -> CredFact | None:
        if not secret or len(secret) > 80 or secret.startswith("/"):
            return None
        for c in self.creds:
            if c.user == user and c.secret == secret:
                cred = c
                break
        else:
            cred = CredFact(user=user[:48], secret=secret[:80],
                            source=source[:80])
            self.creds.append(cred)
        if tested_on:
            cred.tested_on.add(tested_on)
        if valid_on:
            cred.valid_on.add(valid_on)
        return cred

    def _cmd_side(self, cmd: str) -> None:
        """Facts derivable from the command line alone (idempotent)."""
        cmd = cmd or ""
        if cmd in self._seen_cmds:
            return
        if len(self._seen_cmds) > 3000:
            self._seen_cmds.clear()
        self._seen_cmds.add(cmd)
        ips = IP_RE.findall(cmd)
        for ip in ips:
            self.ips_seen.add(ip)
            self.add_host(ip)
        tgt = ips[-1] if ips else None
        if tgt and RECON_RE.search(cmd):
            h = self.add_host(tgt)
            if h:
                h.scans += 1
        src = (tgt or "cmd")[:40]
        for m in _SSHPASS.finditer(cmd):
            self.add_cred("?", m.group(1), src, tested_on=tgt)
        for m in _SMB_U.finditer(cmd):
            self.add_cred(m.group(1), m.group(2), src, tested_on=tgt)
        for m in _MYSQL_U.finditer(cmd):
            self.add_cred(m.group(1), m.group(2), src, tested_on=tgt)
        for m in _URL_CRED.finditer(cmd):
            self.add_cred(m.group(1), m.group(2), src, tested_on=tgt)
        for m in _HYDRA_LP.finditer(cmd):
            self.add_cred(m.group(1), m.group(2), src, tested_on=tgt)

    # ---------- observation paths ----------

    def observe_command(self, cmd: str, *, from_coach: bool = False) -> None:
        """Telemetry command — no output visible. Books write/run attempts as
        pending; mark_run_exit() confirms them when command_result lands."""
        if not cmd:
            return
        self._cmd_side(cmd)
        self._pending = None
        if cmd.startswith("<type>"):
            return   # typed pane input: cred extraction yes, write/run no
        if tgt := _run_target(cmd):
            f = self.files.setdefault(tgt, FileFact(path=tgt, kind=_kind(tgt)))
            f.runs += 1
            self._pending = (tgt, "run", time.time())
        elif w := WRITE_RE.search(cmd):
            path = w.group(1) or w.group(3)
            if path and path != "/dev/null":
                self.files.setdefault(path, FileFact(path=path,
                                                     kind=_kind(path))).attempts += 1
                self._pending = (path, "write", time.time())

    def mark_run_exit(self, code: int) -> None:
        """command_result for a telemetry command — confirm the pending
        write (exit 0 → confirmed write) or attach the run's exit code."""
        if not self._pending:
            return
        path, kind, ts = self._pending
        self._pending = None
        if time.time() - ts > _PENDING_TTL:
            return
        f = self.files.get(path)
        if not f:
            return
        if kind == "run":
            f.last_exit = code
        elif code == 0 and f.writes < f.attempts:
            f.writes += 1

    def observe_output(self, cmd: str, out: str, code: int | None) -> None:
        """Coach exec/type result — full extraction: command-side facts,
        parsed output facts, confirmed write/run bookkeeping."""
        cmd = cmd or ""
        try:
            self._cmd_side(cmd)
            typed_input = cmd.startswith("<type>")
            if not typed_input:
                if w := WRITE_RE.search(cmd):
                    path = w.group(1) or w.group(3)
                    if path and path != "/dev/null" and code == 0:
                        f = self.files.setdefault(
                            path, FileFact(path=path, kind=_kind(path)))
                        f.attempts += 1
                        f.writes += 1
                if tgt := _run_target(cmd):
                    f = self.files.setdefault(
                        tgt, FileFact(path=tgt, kind=_kind(tgt)))
                    f.runs += 1
                    if code is not None:
                        f.last_exit = code
            self.apply_delta(parse_output(cmd, strip_ansi(out or "")))
        except Exception:      # fact extraction must never break a turn
            log.debug("observe_output failed", cmd=(cmd or "")[:120],
                      exc_info=True)

    def apply_delta(self, d: dict, source: str = "") -> None:
        for ip in d.get("ips") or ():
            self.ips_seen.add(ip)
            self.add_host(ip)
        for ip, names in (d.get("names") or {}).items():
            h = self.add_host(ip)
            if h:
                for n in names:
                    if n not in h.names:
                        h.names.add(n)
        for ip, ports in (d.get("ports") or {}).items():
            h = self.add_host(ip)
            if h:
                for p, s in ports.items():
                    h.ports.setdefault(int(p), str(s)[:40])
        for c in d.get("creds") or ():
            self.add_cred(c.get("user") or "?", c.get("secret") or "",
                          c.get("source") or source, valid_on=c.get("host"))
        for f in d.get("findings") or ():
            f = str(f)[:80]
            if f not in self.findings:
                self.findings.append(f)
        del self.findings[:-12]           # bounded — enum lists can be long

    def apply_worker_report(self, worker_id: str, parsed: dict) -> dict:
        """Merge a structured worker report (phase C). Returns merge counts
        so collect_agent can tell the parent what flowed in."""
        n_creds = n_ports = n_findings = 0
        for c in parsed.get("creds") or []:
            if self.add_cred(c.get("user") or "?", c.get("secret") or "",
                             f"{worker_id}", valid_on=c.get("host")):
                n_creds += 1
        for h in parsed.get("hosts") or []:
            ip = h.get("ip") or ""
            hf = self.add_host(ip, h.get("name") or "")
            if hf:
                for p, s in (h.get("ports") or {}).items():
                    try:
                        hf.ports.setdefault(int(p), str(s)[:40])
                        n_ports += 1
                    except (TypeError, ValueError):
                        continue
        for fnd in (parsed.get("findings") or [])[:6]:
            fnd = str(fnd)[:120]
            if fnd not in self.findings:
                self.findings.append(fnd)
                n_findings += 1
        del self.findings[:-12]
        return {"creds": n_creds, "ports": n_ports, "findings": n_findings}

    # ---------- flags (grounding evidence) ----------

    def flag_seen(self, value: str) -> int:
        f = self.flags.setdefault(value, FlagFact())
        f.seen += 1
        return f.seen

    def flag_mark_submitted(self, value: str, ok: bool) -> None:
        f = self.flags.setdefault(value, FlagFact())
        f.submitted = True
        f.accepted = f.accepted or ok

    # ---------- queries for the objective tracker ----------

    def untested_creds(self) -> list[CredFact]:
        return [c for c in self.creds
                if not c.tested_on and not c.valid_on]

    def unscanned(self, targets: list[dict]) -> list[str]:
        out = []
        for t in targets:
            ip = (t.get("ip") or "").split("/")[0]
            name = t.get("name") or ip
            h = self.hosts.get(ip)
            if ip and (not h or h.scans == 0):
                out.append(name)
        return out

    def phase(self, flags_open: int) -> str:
        """Coarse kill-chain position from facts alone."""
        if self.creds and any(c.valid_on for c in self.creds):
            base = "access"
        elif any(h.ports for h in self.hosts.values()):
            base = "foothold"
        elif any(h.scans for h in self.hosts.values()):
            base = "recon"
        else:
            base = "recon"
        return "objectives" if flags_open == 0 else f"{base}→objectives" \
            if base == "access" else base

    # ---------- render ----------

    def render(self, max_chars: int = 1100, *, compact: bool = False) -> str:
        """FACTS: section for the context message. Cred secrets are kept —
        the agent needs them to type passwords; everything else truncates."""
        if not (self.hosts or self.creds or self.files or self.flags):
            return ""
        lines = ["FACTS:"]
        if self.hosts:
            hosts = list(self.hosts.values())[:8]
            if compact:
                txt = " | ".join(h.ip for h in hosts)
            else:
                txt = " | ".join(h.label() for h in hosts)
            if len(self.hosts) > len(hosts):
                txt += f" | +{len(self.hosts) - len(hosts)}"
            lines.append("  hosts: " + txt)
        if self.creds:
            parts = []
            for c in self.creds[:6]:
                if c.valid_on:
                    st = "valid:" + ",".join(sorted(c.valid_on)[:3])
                elif c.tested_on:
                    st = "tried:" + ",".join(sorted(c.tested_on)[:3])
                else:
                    st = "untested"
                parts.append(f"{c.user}/{c.secret} ({st})")
            if len(self.creds) > 6:
                parts.append(f"+{len(self.creds) - 6}")
            lines.append("  creds: " + " | ".join(parts))
        if self.files:
            parts = []
            for f in list(self.files.values())[-6:]:
                if compact:
                    parts.append(f.path)
                    continue
                det = f"{f.writes}w" if f.writes else \
                    (f"{f.attempts}a" if f.attempts else "")
                if f.runs:
                    det += f" {f.runs}r" + \
                        (f"(e{f.last_exit})" if f.last_exit is not None else "")
                parts.append(f"{f.path} {f.kind}({det})" if det
                             else f"{f.path} {f.kind}")
            lines.append("  files: " + " | ".join(parts))
        if self.flags:
            accepted = sum(1 for f in self.flags.values() if f.accepted)
            open_vals = [v for v, f in self.flags.items()
                         if f.seen and not f.accepted]
            seg = f"{accepted} accepted" if accepted else ""
            if open_vals:
                seg += ("; " if seg else "") + \
                    "unsubmitted: " + ", ".join(open_vals[:3])
            lines.append("  flags: " + (seg or "seen only"))
        if self.findings and not compact:
            lines.append("  noted: " + " | ".join(self.findings[-6:]))
        out = "\n".join(lines)
        if len(out) > max_chars and not compact:
            out = self.render(max_chars, compact=True)
        return out[:max_chars]
