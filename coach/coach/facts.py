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
from typing import ClassVar

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
_USER_AT_HOST = re.compile(r"([\w.\-]+)@([\w.\-]+)")
# routing-capable tunnel setup — these change kali's L3 vantage, so
# reachability facts learned pre-tunnel go stale (ssh -D does NOT: a
# SOCKS proxy only helps proxy-aware tools, direct connects stay local)
_ROUTING_SETUP = re.compile(
    r"\b(sshuttle|openvpn|wg-quick|tailscale)\b|\bssh\b[^|&;'\"]*\s-w\d")
_MYSQL_H = re.compile(r"\bmysql\b[^\n]*?-h\s*['\"]?(\S+)")
_SMB_SHARE = re.compile(r"//([\w.\-]+)")
_URL_CRED_HOST = re.compile(r"\w[\w.-]*:[^\s:/@]+@([\w.\-]+)")
_HYDRA_URI = re.compile(r"(?:ssh|ftp|smb|rdp|mysql|vnc|telnet)://([\w.\-]+)")
# auth failures in OUTPUT — a command that exits 0 without any of these
# means the credential in its line actually worked (valid_on)
_AUTH_FAIL_OUT = re.compile(
    r"Access denied|Authentication failed|Permission denied \(publickey|"
    r"Logon failure|Login failed|incorrect password", re.IGNORECASE)
# `sort | uniq -c | sort -rn` output lines — the leading "N <value>" pair is
# top-talker evidence (top attacker IP, hottest user) that MUST survive
# context loss: s54 computed `5 203.0.113.44` correctly, then lost it and
# re-derived the wrong awk field for an hour
_TOPN = re.compile(
    r"^\s*(\d{1,9})\s+((?:\d{1,3}\.){3}\d{1,3}|[\w@:.-]{3,64})\s*$", re.MULTILINE)


def _cmd_creds(cmd: str) -> list[tuple[str, str, str | None]]:
    """(user, secret, target) triples the command line tests. The target
    is per-credential: the sshpass pair authenticates against the ssh
    host while a wrapped `mysql -h` pair is tested on the DATABASE, not
    the pivot (s46 attributed ssh tests to 172.20.1.3)."""
    cmd = cmd or ""
    ssh = _USER_AT_HOST.search(cmd)
    ssh_host = ssh.group(2) if ssh else None
    ips = IP_RE.findall(cmd)
    last_ip = ips[-1] if ips else None
    pairs: list[tuple[str, str, str | None]] = []
    for m in _SSHPASS.finditer(cmd):
        pairs.append(("?", m.group(1), ssh_host or last_ip))
    for m in _SMB_U.finditer(cmd):
        share = _SMB_SHARE.search(cmd)
        pairs.append((m.group(1), m.group(2),
                      (share.group(1) if share else ssh_host) or last_ip))
    for m in _MYSQL_U.finditer(cmd):
        mh = _MYSQL_H.search(cmd)
        pairs.append((m.group(1), m.group(2),
                      (mh.group(1).strip("'\"") if mh else ssh_host)
                      or last_ip))
    for m in _URL_CRED.finditer(cmd):
        uh = _URL_CRED_HOST.search(cmd)
        pairs.append((m.group(1), m.group(2),
                      (uh.group(1) if uh else ssh_host) or last_ip))
    for m in _HYDRA_LP.finditer(cmd):
        hu = _HYDRA_URI.search(cmd)
        pairs.append((m.group(1), m.group(2),
                      (hu.group(1) if hu else None) or ssh_host or last_ip))
    return pairs

_SCRIPT_EXT = re.compile(r"\.(py|sh|pl|rb|php|ps1|lua|js|expect)$")
_PENDING_TTL = 60.0     # mirrors SessionState.mark_exit freshness guard


def _kind(path: str) -> str:
    if _SCRIPT_EXT.search(path):
        return "script"
    if re.search(r"loot|flag|creds?|dump|hash|passwd|secret", path, re.IGNORECASE):
        return "loot"
    return "out"


# direct script execution without an interpreter — `/root/r.sh`, `./r.sh`,
# `sudo /opt/x.py` (s54: `/root/report.sh` runs never counted as runs).
# Segment-start anchor only: a path after `>`/`<<` is a write target.
_DIRECT_RUN = re.compile(
    r"(?:^|[|;&(]\s*|\b(?:then|do|&&|\|\|)\s+)(?:sudo\s+)?"
    r"((?:\.?/)[\w.+-]+(?:/[\w.+-]+)*\.(?:sh|py|pl|rb|js))\b")


def _run_target(cmd: str) -> str | None:
    """Script path of an interpreter invocation — skips flag args so
    `python3 -u x.py` lands on x.py, not -u (the old regex counted -u)."""
    m = RUN_RE.search(cmd or "")
    if not m:
        m2 = _DIRECT_RUN.search(cmd or "")
        return m2.group(1) if m2 else None
    for tok in cmd[m.end():].split():
        if tok == "-c":
            return None      # sh -c 'inline': the inline string isn't a file
        if not tok.startswith("-"):
            return tok
    return None


def file_host(cmd: str) -> str | None:
    """The remote host a command targets, or None for local commands.
    `ssh user@host 'cat /tmp/x'` reads x ON host — a host-blind file key
    made s46's agent search Kali's /tmp for loot written on shop01."""
    m = _USER_AT_HOST.search(cmd or "")
    return m.group(2) if m else None


def file_key(cmd: str, path: str) -> str:
    """Facts key for a filesystem path — '@host' suffix when the command
    runs remotely, so the same path on different hosts stays distinct and
    the rendered fact tells the model WHERE the file lives."""
    h = file_host(cmd)
    return f"{path}@{h}" if h else path


@dataclass
class HostFact:
    ip: str
    names: set[str] = field(default_factory=set)
    ports: dict[int, str] = field(default_factory=dict)
    scans: int = 0            # recon commands aimed at this host

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
    reads: int = 0                        # cat/grep/… hits — re-read guard
    # mutation_seq snapshot when `reads` was last reset — a file re-read
    # after any confirmed write/run is FRESH content, not a settled loop
    read_seq: int = -1
    # checkfail_seq snapshot at the last confirmed write — a rewrite after a
    # NEWLY failed check is informed iteration, not 'perfecting' (s54: the
    # script ran clean but its OUTPUT was wrong; only check_flag knew)
    write_check_seq: int = -1
    # runs snapshot at the last write — a version that was RUN since writing
    # produced observable output; rewriting it is informed iteration (s54:
    # write->run->inspect->rewrite is THE deliverable loop)
    write_run_seq: int = 0
    last_exit: int | None = None


# read-commands — also matched after a quote/;|& boundary so ssh-wrapped
# `'cat /etc/x'` counts (the old ^-anchor missed every pivot read on s46)
READ_CMD = re.compile(
    r"(?:^|['\";|&]\s*)(?:sudo\s+)?(?:cat|less|more|head|tail|grep|egrep|"
    r"fgrep|awk|sed|cut|sort|uniq|wc|strings|file|ls|ll|xxd|od|diff)\b")
_ABS_PATH = re.compile(r"(?<![\w.:/-])/(?:[\w.+-]+/)*[\w.+-]+")
# a path only counts as read when it sits in the SAME segment as the read
# command — `cd /tmp && find x | head` reads nothing (s46: /tmp was counted)
_SEG_SPLIT = re.compile(r"\|\||&&|[|;&]")
# redirect targets (`2>/dev/null`) are destinations, not reads (s46: /dev/null
# was counted 11x as 'read' because it out-lengthed the real path)
_REDIRECT = re.compile(r"\d?>>?\s*\S+")


def read_target(cmd: str) -> str | None:
    """Longest absolute path in a read-command segment, or None. Write
    redirects (`cat > f`, heredocs, tee) write — they don't count as reads."""
    cmd = cmd or ""
    if not READ_CMD.search(cmd) or WRITE_RE.search(cmd):
        return None
    best = None
    for seg in _SEG_SPLIT.split(cmd):
        seg = seg.strip(" '\"")
        if not READ_CMD.search(seg):
            continue
        paths = [p for p in _ABS_PATH.findall(_REDIRECT.sub(" ", seg))
                 if p != "/dev/null"]
        if paths and (cand := max(paths, key=len)) \
                and (best is None or len(cand) > len(best)):
            best = cand
    return best


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
        # typed vulnerability records (worker "vulns" key + record_finding
        # tool): {id,title,sev,host,status,evidence,next,owner} — the string
        # findings stay the lightweight catch-all, these are report-grade
        self.vulns: list[dict] = []
        self._vuln_seq = 0
        self.denials: list[str] = []      # bounded dead ends (denied:svc@host)
        self.caps: list[str] = []         # proven primitives (root-exec via …)
        self.lessons: list[str] = []      # agent-authored lessons (record_lesson)
        # observer field notes — {id,text,tags} from coach_lessons; never
        # rendered into the prompt, consumed via lookup_guide + push-hints
        self.field_notes: list[dict] = []
        # — bounded: the agent's own distilled knowledge, replayed into the
        # store from coach_actions on restart so it survives context loss
        self._pending: tuple[str, str, float] | None = None  # (path, kind, ts)
        self._seen_cmds: set[str] = set()   # dedup: replay + live overlap
        self.mutation_seq = 0             # bumps on every confirmed write/run
        self.checkfail_seq = 0            # bumps on every failed check_flag

    def _count_read(self, cmd: str, rt: str) -> FileFact:
        """Read bookkeeping with freshness reset: when the fs mutation counter
        moved since this file's last read, its content is NEW — reset the
        re-read budget (s54: report.txt regenerated by report.sh stayed
        denied at '3x same result' though every run rewrote it)."""
        key = file_key(cmd, rt)
        f = self.files.setdefault(key, FileFact(path=key, kind=_kind(rt)))
        if f.read_seq != self.mutation_seq:
            f.reads = 0
            f.read_seq = self.mutation_seq
        f.reads += 1
        return f

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
            # bookkeeping only — a command-line IP is intent, not discovery;
            # whitelisting it would let a hallucinated IP self-authorize
            self.add_host(ip)
        if ips and RECON_RE.search(cmd):
            h = self.add_host(ips[-1])
            if h:
                h.scans += 1
        for user, secret, tgt in _cmd_creds(cmd):
            self.add_cred(user, secret, (tgt or "cmd")[:40], tested_on=tgt)

    # ---------- observation paths ----------

    def observe_command(self, cmd: str) -> None:
        """Telemetry command — no output visible. Books write/run attempts as
        pending; mark_run_exit() confirms them when command_result lands."""
        if not cmd:
            return
        self._cmd_side(cmd)
        self._pending = None
        if cmd.startswith("<type>"):
            return   # typed pane input: cred extraction yes, write/run no
        if tgt := _run_target(cmd):
            key = file_key(cmd, tgt)
            f = self.files.setdefault(key, FileFact(path=key,
                                                    kind=_kind(tgt)))
            f.runs += 1
            self.mutation_seq += 1
            self._pending = (key, "run", time.time())
        elif w := WRITE_RE.search(cmd):
            path = (w.group(1) or w.group(3) or "").strip("'\"")
            if path and path != "/dev/null":
                key = file_key(cmd, path)
                self.files.setdefault(key, FileFact(path=key,
                                                    kind=_kind(path))).attempts += 1
                self._pending = (key, "write", time.time())
        if rt := read_target(cmd):
            self._count_read(cmd, rt)

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
            self.mutation_seq += 1
        elif code == 0 and f.writes < f.attempts:
            f.writes += 1
            f.write_check_seq = self.checkfail_seq
            f.write_run_seq = f.runs
            self.mutation_seq += 1

    def observe_output(self, cmd: str, out: str, code: int | None) -> None:
        """Coach exec/type result — full extraction: command-side facts,
        parsed output facts, confirmed write/run bookkeeping."""
        cmd = cmd or ""
        try:
            self._cmd_side(cmd)
            typed_input = cmd.startswith("<type>")
            if not typed_input:
                if w := WRITE_RE.search(cmd):
                    # the \S+ capture can eat a closing quote (`>> /f"`) —
                    # strip it or dedup/promotion keys diverge from the
                    # unquoted path the cron output shows (s46-promotion bug)
                    path = (w.group(1) or w.group(3) or "").strip("'\"")
                    if path and path != "/dev/null" and code == 0:
                        key = file_key(cmd, path)
                        f = self.files.setdefault(
                            key, FileFact(path=key, kind=_kind(path)))
                        f.attempts += 1
                        f.writes += 1
                        f.write_check_seq = self.checkfail_seq
                        f.write_run_seq = f.runs
                        self.mutation_seq += 1
                if tgt := _run_target(cmd):
                    key = file_key(cmd, tgt)
                    f = self.files.setdefault(
                        key, FileFact(path=key, kind=_kind(tgt)))
                    f.runs += 1
                    self.mutation_seq += 1
                    if code is not None:
                        f.last_exit = code
                if (rt := read_target(cmd)) and code == 0:
                    # only successful reads settle a file — a failed wrapper
                    # (ssh -J auth hang, sudo denial, missing interpreter)
                    # returns prompt/error text, not content; counting it
                    # locks the path out at 'already read 3x' (s72: db.txt
                    # denied though never actually read)
                    self._count_read(cmd, rt)
            parsed = parse_output(cmd, strip_ansi(out or ""))
            self.apply_delta(parsed)
            # a routing-capable tunnel changes kali's vantage — drop stale
            # reachability dead-ends or they keep bricking now-valid
            # connects (s84: sshuttle up, but filtered:app01@kali from the
            # pre-tunnel scan still denied the direct ssh that worked).
            # False-clear is self-healing: a real dead end re-earns the
            # fact on the next failed probe.
            if code == 0 and _ROUTING_SETUP.search(cmd):
                kept = [d for d in self.denials
                        if not (d.startswith(("filtered:", "unreachable:"))
                                and d.endswith("@kali"))]
                if len(kept) != len(self.denials):
                    self.denials = kept
                    self.mutation_seq += 1
            # loot digest: a file read that yielded secrets/leads leaves a
            # one-line token digest — the model sees the contents are already
            # consumed instead of re-cat'ing the file after context loss
            if (rt := read_target(cmd)) and code == 0:
                toks = [c["user"] for c in parsed.get("creds") or ()][:3]
                toks += [str(f).split(":", 1)[1].split("=")[0]
                         for f in (parsed.get("findings") or ())
                         if "=" in str(f) and ":" in str(f)][:3]
                if toks:
                    base = rt.rsplit("/", 1)[-1]
                    tag = f"loot:{base}→{','.join(toks)[:48]}"
                    if not any(f.startswith(f"loot:{base}")
                               for f in self.findings):
                        self.findings.append(tag[:80])
            # top-talker counts persist as findings — computed evidence that
            # outlives context windows (s54: '5 203.0.113.44' was derived
            # once, lost, then re-derived WRONG for an hour)
            if code == 0 and not typed_input:
                top = _TOPN.search(out or "")
                if top:
                    tag = f"top:{top.group(1)}x{top.group(2)}"
                    if tag not in self.findings:
                        self.findings.append(tag[:80])
            # a credential test that exits 0 without an auth-failure marker
            # worked — mark it valid so `tried:` becomes `valid:` and the
            # model stops stuffing it at unrelated services
            if (code == 0 and not typed_input
                    and not _AUTH_FAIL_OUT.search(strip_ansi(out or ""))):
                for user, secret, host in _cmd_creds(cmd):
                    if host:
                        self.add_cred(user, secret, valid_on=host)
            # root-cron promotion: a crontab line for a file WE wrote proves
            # root code-exec (not just a discovered schedule) — the cap must
            # outlive the history that produced it
            for entry in parsed.get("cap_cron") or ():
                # entry is 'path@host' — the file's key when its write ran
                # through ssh to that host; bare-path fallback for local or
                # un-attributed writes
                path = str(entry).split("@", 1)[0]
                ff = self.files.get(str(entry)) or self.files.get(path)
                if ff and ff.writes:
                    self._merge_caps([f"root-exec via {entry}"])
            # timeout with no marker text — curl exit 28 on an empty reply
            # is the unreachable-host signal too (s46: direct curls to a
            # docker-internal IP retried every restart)
            if code == 28:
                ssh = _USER_AT_HOST.search(cmd)
                h = ssh.group(2) if ssh else "kali"
                ips = [i for i in IP_RE.findall(cmd) if i != h]
                tgt = ips[-1] if ips else h
                dn = f"unreachable:{tgt}@{h}"
                if dn not in self.denials:
                    self.denials.append(dn)
                del self.denials[:-24]
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
        for dn in d.get("denials") or ():
            dn = str(dn)[:64]
            if dn not in self.denials:
                self.denials.append(dn)
        del self.denials[:-24]
        self._merge_caps(d.get("caps") or ())

    def add_lesson(self, text: str, source: str = "main") -> int:
        """record_lesson — agent-authored session knowledge. Distinct from
        findings (output-derived evidence): these are the model's own
        distilled rules-of-thumb for THIS session ('app01 needs Bearer
        token from /portal/config.js'). Bounded and deduped."""
        t = str(text or "").strip()[:160]
        if not t:
            return len(self.lessons)
        entry = f"{t}" if source == "main" else f"[{source}] {t}"
        if entry not in self.lessons:
            self.lessons.append(entry)
        del self.lessons[:-10]
        return len(self.lessons)

    def set_field_notes(self, notes) -> None:
        """Observer field notes from session_context — kept in memory for
        lookup_guide union search and tag-matched push-hints. Never rendered
        into the prompt (the user's call: pull/push only)."""
        out = []
        for n in notes or []:
            if not isinstance(n, dict) or not n.get("text"):
                continue
            out.append({"id": int(n.get("id") or 0),
                        "text": str(n["text"])[:240],
                        "tags": [str(t)[:32] for t in (n.get("tags") or [])][:8]})
        self.field_notes = out[-24:]

    def _merge_caps(self, entries) -> None:
        for cp in entries:
            cp = str(cp)[:80]
            if cp not in self.caps:
                self.caps.append(cp)
        del self.caps[:-6]

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
        n_vulns = 0
        for v in (parsed.get("vulns") or [])[:8]:
            if self._merge_vuln(v, worker_id):
                n_vulns += 1
        return {"creds": n_creds, "ports": n_ports, "findings": n_findings,
                "vulns": n_vulns}

    # ---------- typed findings (vulns) ----------

    _VULN_SEV: ClassVar = {"info", "low", "medium", "high", "critical"}
    _VULN_STATUS: ClassVar = {
        # candidate: a suspicion/signature — needs proof before it counts
        "hypothesis": "candidate", "candidate": "candidate",
        "suspected": "candidate", "possible": "candidate",
        # confirmed: reproduced/validated — the only report-grade state
        "confirmed": "confirmed", "validated": "confirmed",
        "proven": "confirmed", "verified": "confirmed",
        # rejected: disproven — kept so the dead end isn't re-chased
        "rejected": "rejected", "false-positive": "rejected",
        "false_positive": "rejected", "dead": "rejected",
    }

    def _norm_vuln_status(self, raw: str) -> str:
        return self._VULN_STATUS.get(str(raw or "").strip().lower(),
                                     "candidate")

    def _merge_vuln(self, v: dict, owner: str) -> bool:
        """Create or update one typed finding. Dedup key is title+host —
        a re-report upgrades status/evidence (validation flow); a 'confirmed'
        row without concrete evidence is auto-demoted to candidate (the
        XBOW rule: proof is what separates a finding from a guess)."""
        if not isinstance(v, dict) or not v.get("title"):
            return False
        rec = {"title": str(v["title"])[:100],
               "sev": str(v.get("sev") or "info").lower()[:16],
               "host": str(v.get("host") or "")[:60],
               "status": self._norm_vuln_status(v.get("status") or ""),
               "evidence": str(v.get("evidence") or "")[:200],
               "next": str(v.get("next") or "")[:120],
               "owner": str(v.get("owner") or owner)[:12]}
        if rec["sev"] not in self._VULN_SEV:
            rec["sev"] = "info"
        if rec["status"] == "confirmed" and len(rec["evidence"]) < 12:
            rec["status"] = "candidate"      # claim without proof demotes
        old = next((o for o in self.vulns
                    if o["title"] == rec["title"]
                    and o["host"] == rec["host"]), None)
        if old is not None:
            _sev_ord = {s: i for i, s in enumerate(
                ["info", "low", "medium", "high", "critical"])}
            new_sev = rec.pop("sev")
            old.update({k: v for k, v in rec.items() if v != ""})
            # dedup-merge keeps the STRONGER severity — a re-report naming
            # no sev must not silently downgrade (intentional downgrades
            # go through the id-update path)
            if _sev_ord.get(new_sev, 0) > _sev_ord.get(old["sev"], 0):
                old["sev"] = new_sev
            return False                     # merged into an existing row
        self._vuln_seq += 1
        rec["id"] = f"v{self._vuln_seq}"
        self.vulns.append(rec)
        del self.vulns[:-24]
        return True

    def apply_finding(self, args: dict, owner: str = "main") -> dict | None:
        """record_finding tool — id → update that row; no id → dedup on
        title+host then create. Returns the row so the tool result can
        name the stable id back to the model."""
        args = args or {}
        vid = str(args.get("id") or "").strip()
        if vid:
            row = next((v for v in self.vulns if v["id"] == vid), None)
            if row is None:
                return None
            st = self._norm_vuln_status(args.get("status") or row["status"])
            ev = str(args.get("evidence") or row["evidence"])[:200]
            if st == "confirmed" and len(ev) < 12:
                st = "candidate"
            row.update({
                "status": st, "evidence": ev,
                "sev": (str(args.get("sev") or row["sev"]).lower()[:16]
                        if str(args.get("sev") or "").lower()[:16]
                        in self._VULN_SEV else row["sev"]),
                "next": str(args.get("next") or row["next"])[:120],
                "title": str(args.get("title") or row["title"])[:100],
                "host": str(args.get("host") or row["host"])[:60]})
            return row
        args = dict(args)
        args.pop("id", None)
        args.setdefault("owner", owner)
        before = len(self.vulns)
        self._merge_vuln(args, owner)
        if len(self.vulns) > before:
            return self.vulns[-1]
        return next((o for o in self.vulns
                     if o["title"] == str(args.get("title") or "")[:100]
                     and o["host"] == str(args.get("host") or "")[:60]), None)

    def report(self, scope: dict | None = None,
               coverage_rows: dict | None = None,
               title: str = "Penetration Test Report") -> str:
        """Deterministic engagement-report draft — findings grouped by
        validation state so the deliverable can't silently ship candidates
        as confirmed. Bounded rows (24 vulns / 16 hosts / 16 creds)."""
        L = [f"# {title}", ""]
        if scope and scope.get("locked"):
            L += [f"**Authorized scope** ({scope.get('authorized_by', '?')}): "
                  f"{', '.join(scope.get('nets') or [])}"
                  + (f" | hosts: {', '.join(scope.get('hosts') or [])}"
                     if scope.get("hosts") else ""),
                  ""]
        conf = [v for v in self.vulns if v["status"] == "confirmed"]
        cand = [v for v in self.vulns if v["status"] == "candidate"]
        L += ["## Findings", ""]
        if conf:
            for v in conf:
                L.append(f"### [{v['id']}] {v['title']} — {v['sev'].upper()}"
                         + (f" on {v['host']}" if v["host"] else ""))
                if v["evidence"]:
                    L.append(f"- Evidence: {v['evidence']}")
                if v["next"]:
                    L.append(f"- Next/remediation: {v['next']}")
                L.append("")
        else:
            L += ["No confirmed findings.", ""]
        if cand:
            L += ["## Candidates (unvalidated)", ""]
            L += [f"- [{v['id']}] {v['title']}"
                  + (f" on {v['host']}" if v["host"] else "")
                  + (f" — {v['evidence'][:80]}" if v["evidence"] else "")
                  for v in cand]
            L.append("")
        rej = [v for v in self.vulns if v["status"] == "rejected"]
        if rej:
            L += ["## Tested & ruled out", ""]
            L += [f"- {v['title']}" + (f" on {v['host']}" if v["host"] else "")
                  for v in rej]
            L.append("")
        if coverage_rows:
            open_rows = [r for r in coverage_rows.values()
                         if r.get("outcome") in ("untested", "testing")]
            L += [(f"## Coverage — {len(coverage_rows)} surfaces, "
                   f"{len(open_rows)} still open"), ""]
        if self.hosts:
            L += ["## Hosts & services", ""]
            for ip, h in list(self.hosts.items())[:16]:
                name = min(h.names) if h.names else ""
                ports = ", ".join(f"{p}/{s}" for p, s in
                                  sorted(h.ports.items())[:12])
                L.append(f"- {ip}"
                         + (f" ({name})" if name else "")
                         + (f": {ports}" if ports else ""))
            L.append("")
        if self.creds:
            L += ["## Access obtained", ""]
            L += [f"- {c.user}:{c.secret} "
                  + (f"→ {', '.join(sorted(c.valid_on))}"
                     if c.valid_on else "")
                  for c in self.creds[:16]]
            L.append("")
        return "\n".join(L)

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

    # ---------- render ----------

    def render(self, max_chars: int = 1100, *, compact: bool = False) -> str:
        """FACTS: section for the context message. Cred secrets are kept —
        the agent needs them to type passwords; everything else truncates."""
        if not (self.hosts or self.creds or self.files or self.flags
                or self.denials or self.caps or self.lessons):
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
                if f.reads:
                    det += f" {f.reads}rd"
                parts.append(f"{f.path} {f.kind}({det})" if det
                             else f"{f.path} {f.kind}")
            lines.append("  files: " + " | ".join(parts))
        if self.flags:
            accepted = sum(1 for f in self.flags.values() if f.accepted)
            open_vals = [v for v, f in self.flags.items()
                         if f.seen and not f.submitted]
            rejected = [v for v, f in self.flags.items()
                        if f.submitted and not f.accepted]
            seg = f"{accepted} accepted" if accepted else ""
            if open_vals:
                seg += ("; " if seg else "") + \
                    "unsubmitted: " + ", ".join(open_vals[:3])
            if rejected:
                seg += ("; " if seg else "") + \
                    "rejected: " + ", ".join(rejected[:3])
            lines.append("  flags: " + (seg or "seen only"))
        if self.caps:
            # proven primitives are the highest-value line — they are what
            # stops re-deriving a solved technique from scratch after
            # context loss (s46: root-cron reuse lagged its proof by ~65min)
            lines.append("  caps: " + " | ".join(self.caps[-3:] if compact
                                                 else self.caps[-6:]))
        if self.lessons:
            # agent-authored session knowledge — the model's own distilled
            # lessons outrank derived evidence; rendered near the top so a
            # post-restart turn acts on them immediately
            kept = self.lessons[-4:] if compact else self.lessons[-8:]
            lines.append("  lessons: " + " | ".join(kept))
        if self.denials:
            # dead ends deserve permanent space — they are what stops the
            # model re-trying sudo/docker/mysql paths that already failed
            blocked = self.denials[-4:] if compact else self.denials[-8:]
            lines.append("  blocked: " + " | ".join(blocked))
        if self.findings:
            noted = self.findings[-4:] if compact else self.findings[-6:]
            lines.append("  noted: " + " | ".join(noted))
        if self.vulns:
            kept = self.vulns[-2:] if compact else self.vulns[-4:]
            lines.append(
                "  vulns: " + " | ".join(
                    f"{v['id']}:{v['title']}@{v['host'] or '?'}"
                    f"({v['sev']},{v['status']})"
                    for v in kept))
        out = "\n".join(lines)
        if len(out) > max_chars and not compact:
            out = self.render(max_chars, compact=True)
        return out[:max_chars]
