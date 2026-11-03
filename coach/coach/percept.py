"""Perceptor — deterministic normalization of exec/type output.

Two jobs, zero LLM calls:
  parse_output  — extract a facts delta (hosts, hostnames, ports, creds)
                  from raw pane text; FactsDB.apply_delta merges it.
  normalize     — produce the compact tool reply the model sees: ANSI-free,
                  elided middle, exit-code suffix, a status tag the loop can
                  act on (ok | error | no_change | busy).

Everything parsed here is *untrusted tool output* — it feeds facts and the
model's context but is never executed and never trusted as instructions.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger(__name__)

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# ANSI escapes + control bytes that survive tmux capture-pane — left in,
# they pollute the context with garbage tokens
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][0-9A-B]|\x1b[=>]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s or "")


# ---------- tool-specific parsers (first-token dispatch) ----------
# every parser fills the same delta dict:
#   ips:    {ip,...}            any IP literal seen
#   names:  {ip: [hostname]}    name resolutions observed
#   ports:  {ip: {port: svc}}   open services observed
#   creds:  [{user,secret,host}] credentials observed
#   findings: [short strings]   notable lines worth a host note
#   denials:  [short strings]   dead ends: service/permission refused

_NMAP_REPORT = re.compile(
    r"Nmap scan report for\s+(?:(\S+)\s+)?\(?((?:\d{1,3}\.){3}\d{1,3})\)?")
_NMAP_PORT = re.compile(
    r"^(\d{1,5})/(tcp|udp)\s+open\s+(\S+)(?:\s{2,}(.+))?$")
_MASSCAN = re.compile(r"Discovered open port\s+(\d+)/(tcp|udp)\s+on\s+(\S+)")
# hydra/medusa success lines:
#   [22][ssh] host: 10.0.0.5   login: svc   password: Backup2024!
_HYDRA = re.compile(
    r"host:\s*(\S+)\s+login:\s*(\S+)\s+password:\s*(\S+)", re.IGNORECASE)
# generic credential pairs — loot files, configs, `hydra -l x -p y` output,
# found passwords dumps
_CRED_PAIR = re.compile(
    r"(?:login|user|username)[:=]\s*([\w.\\-]{1,48})[\s,;|]+"
    r"pass(?:word|wd)?[:=]\s*(\S{1,80})", re.IGNORECASE)
# getent hosts / ping-style resolution:  "10.1.10.21  api01 pentrain-api01"
_GETENT = re.compile(
    r"^\s*((?:\d{1,3}\.){3}\d{1,3})\s+([a-zA-Z][\w. -]*\S)\s*$")
# enum4linux / rpcclient user dumps: "user: svc-backup"
_ENUM_USER = re.compile(r"^(?:user|account|sid-user)[:=]\s*([\w.\\-]{1,48})\s*$",
                        re.IGNORECASE)
# env/config-style secrets — `API_TOKEN=x`, `DEPLOY_PASS=y`, `DB_PASSWORD=z`.
# Looted config.env/dotenv backups are the canonical capstone foothold and
# the generic user/pass pair misses them (no "user" keyword nearby).
_ENV_SECRET = re.compile(
    r"\b([A-Z][A-Z0-9_]{1,38}(?:TOKEN|PASS|PASSWORD|SECRET|APIKEY|API_KEY|"
    r"AUTH|CRED)[A-Z0-9_]*)\s*=\s*['\"]?([^\s'\";}]{3,80})")
# env-style endpoint assignments — `API_URL=http://172.17.0.4:9000` etc.
# The bare IP already lands in ips; the finding carries WHICH service the
# internal URL belongs to so it reads as a lead, not noise.
_ENV_URL = re.compile(
    r"\b([A-Z][A-Z0-9_]{1,38}(?:URL|URI|ENDPOINT)[A-Z0-9_]*)\s*=\s*['\"]?"
    r"((?:https?|ftp|socks[45])://[^\s'\";}]+)")

# permission/service dead ends — recorded as facts so a restart (or a long
# turn chain) doesn't send the model down paths that already failed.
# Deliberately narrow: generic "Permission denied" matches find-output noise.
_SUDOERS = re.compile(r"is not in the sudoers", re.IGNORECASE)
_DOCKER_DENIED = re.compile(
    r"permission denied[^.]*docker|Cannot connect to the Docker daemon",
    re.IGNORECASE)
_ACCESS_DENIED_USER = re.compile(
    r"Access denied for user\s+'?([\w.\-]+)'?", re.IGNORECASE)
_AUTH_FAIL = re.compile(
    r"Authentication failed|Permission denied \(publickey|"
    r"Logon failure|Login failed", re.IGNORECASE)
# retryable friction, not a dead end — lands as a hint, never `denied:`.
# s46 spent 4 execs on `sudo` over ssh before finding `sudo -S`.
_TTY_REQ = re.compile(
    r"a terminal is required|sudo: no tty|sudo: unable to allocate pty", re.IGNORECASE)
# a host that TIMES OUT / has no route is unreachable from this vantage —
# distinct from auth-denied (reachable, wrong cred). Without this fact the
# model re-curls docker-internal IPs directly after every restart (s46: 4x).
_UNREACHABLE = re.compile(
    r"Connection timed out|No route to host|connect: Network is unreachable|"
    r"Operation timed out|Failed to connect .* timed out", re.IGNORECASE)
# curl's own exit-code vocabulary when stderr is empty (28=timeout, 7=refused
# is NOT unreachable — refused means the host answered)
_CURL_TIMEOUT_EXIT = 28

# proven-primitive detectors → `caps:` facts. Distinct from `creds.valid_on`
# (access) — caps are *capabilities* the model must reuse for later objectives
# instead of re-deriving them from history (s46: root-cron was proven at
# 22:18, reused for flag-4 only at 23:24).
# `id` with an explicit user arg also prints uid=0 — not a shell capability.
_UID0 = re.compile(r"uid=0\b")
_ID_USER_ARG = re.compile(r"\bid\s+[\w.\-]+\s*['\"]?$")
# GRANT … FILE ON db.* TO 'user'@'%' → mysql-file capability bound to the
# cred — two patterns: a lazy optional tail lets the engine skip the user
_GRANT_FILE = re.compile(r"GRANT\b[^\n]*?\bFILE\b", re.IGNORECASE)
_GRANT_FILE_TO = re.compile(
    r"GRANT\b[^\n]*?\bFILE\b[^\n]*?\bTO\s+'?([\w.\-]+)'?", re.IGNORECASE)
# crontab line `*/2 * * * * root /path` — emitted as a PROMOTION CANDIDATE:
# facts only grants the cap once the file carries a proven write (w:)
_CRON_ROOT = re.compile(
    r"^\s*[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+"
    r"\s+root\s+(/\S+)", re.MULTILINE)


def _p_caps(cmd: str, out: str, d: dict) -> None:
    h = _denial_host(cmd)
    if _UID0.search(out) and not _ID_USER_ARG.search(cmd or ""):
        d["caps"].append(f"root-shell@{h}")
    for m in _GRANT_FILE_TO.finditer(out):
        d["caps"].append(f"mysql-file:{m.group(1)}")
    if _GRANT_FILE.search(out) and not _GRANT_FILE_TO.search(out):
        d["caps"].append("mysql-file")
    for m in _CRON_ROOT.finditer(out):
        d["cap_cron"].append(f"{m.group(1)}@{h}")
_SSH_TARGET = re.compile(r"([\w.\-]+)@([\w.\-]+)")
_MYSQL_H = re.compile(r"\bmysql\b[^\n]*?-h\s*['\"]?(\S+)")
_SVC_BINARIES = (
    "mysql", "mariadb", "psql", "redis-cli", "mongosh", "smbclient",
    "rpcclient", "evil-winrm", "winrm", "ssh", "ftp", "rdp", "xfreerdp")


def _denial_host(cmd: str) -> str:
    """Best-effort host for a denial — the ssh pivot target (first
    user@host in the command), a mysql -h argument, else the last IP."""
    m = _SSH_TARGET.search(cmd or "")
    if m:
        return m.group(2)
    mh = _MYSQL_H.search(cmd or "")
    if mh:
        return mh.group(1).strip("'\"; ")
    ips = _IP_RE.findall(cmd or "")
    return ips[-1] if ips else "kali"


def _denial_svc(cmd: str) -> str:
    cmd = cmd or ""
    for b in _SVC_BINARIES:
        if re.search(rf"\b{re.escape(b)}\b", cmd):
            return b.split("-")[0]
    return _tool_token(cmd) or "svc"


def _p_denials(cmd: str, out: str, d: dict) -> None:
    h = _denial_host(cmd)
    svc = _denial_svc(cmd)
    if _SUDOERS.search(out):
        d["denials"].append(f"denied:sudo@{h}")
    if _DOCKER_DENIED.search(out):
        d["denials"].append(f"denied:docker@{h}")
    for m in _ACCESS_DENIED_USER.finditer(out):
        d["denials"].append(f"denied:{svc}-{m.group(1)}@{h}")
    if _AUTH_FAIL.search(out):
        d["denials"].append(f"denied:{svc}-auth@{h}")
    if _TTY_REQ.search(out) and "sudo" in (cmd or ""):
        d["findings"].append(
            "hint:sudo needs a pipe — echo $PASS | sudo -S -l")
    if _UNREACHABLE.search(out):
        # the unreachable TARGET is the cmd IP that isn't the ssh pivot —
        # `ssh deploy@shop01 'curl 172.20.1.2'` → 172.20.1.2 unreachable
        # FROM shop01's vantage (docker-internal net)
        ips = [i for i in _IP_RE.findall(cmd or "") if i != h]
        target = ips[-1] if ips else h
        d["denials"].append(f"unreachable:{target}@{h}")
    if re.search(r"\bnmap\b", cmd or ""):
        # a scan that proves ports exist but every one is filtered/closed =
        # ACL/tier isolation from THIS vantage — a fact workers and
        # post-restart turns must inherit or they rescan the dead host
        # forever (s84: w1 ran 4 nmap variants at a filtered app01)
        vm = _SSH_TARGET.search(cmd or "")
        vantage = vm.group(2) if vm else "kali"
        for blk in re.split(r"(?=Nmap scan report for)", out):
            m = _NMAP_REPORT.search(blk)
            if not m:
                continue
            ip = m.group(2)
            opens = len(re.findall(
                r"^\d{1,5}/(?:tcp|udp)\s+open\b", blk, re.MULTILINE))
            filtered = len(re.findall(
                r"^\d{1,5}/(?:tcp|udp)\s+(?:filtered|closed)\b",
                blk, re.MULTILINE))
            if opens == 0 and filtered >= 5:
                d["denials"].append(f"filtered:{ip}@{vantage}")


def _p_nmap(out: str, d: dict) -> None:
    cur: str | None = None
    for ln in out.splitlines():
        m = _NMAP_REPORT.search(ln)
        if m:
            cur = m.group(2)
            if m.group(1):
                d["names"].setdefault(cur, []).append(m.group(1))
            continue
        pm = _NMAP_PORT.match(ln.strip())
        if pm and cur:
            svc = (pm.group(4) or pm.group(3) or "").strip()[:40]
            d["ports"].setdefault(cur, {})[int(pm.group(1))] = svc or pm.group(3)


def _p_masscan(out: str, d: dict) -> None:
    for m in _MASSCAN.finditer(out):
        d["ports"].setdefault(m.group(3), {})[int(m.group(1))] = ""


def _p_hydra(out: str, d: dict) -> None:
    for m in _HYDRA.finditer(out):
        d["creds"].append({"user": m.group(2), "secret": m.group(3),
                           "host": m.group(1)})


def _p_getent(out: str, d: dict) -> None:
    for ln in out.splitlines():
        m = _GETENT.match(ln)
        if m:
            for name in m.group(2).split():
                if name and name not in ("ip6-localhost",):
                    d["names"].setdefault(m.group(1), []).append(name)


def _p_generic(out: str, d: dict) -> None:
    for m in _CRED_PAIR.finditer(out):
        d["creds"].append({"user": m.group(1), "secret": m.group(2),
                           "host": None})
    # hidden form inputs (user_token/csrf/_token) — the auth blocker the
    # model kept missing: the token lands in findings with its VALUE, so
    # including it in the POST takes no reasoning step at all
    for tag in _HIDDEN_TAG.finditer(out):
        nm = _ATTR_NAME.search(tag.group(0))
        vm = _ATTR_VALUE.search(tag.group(0))
        if nm and len(d["findings"]) < 8:
            d["findings"].append(
                f"form:{nm.group(1)}={(vm.group(1) if vm else '')[:64]}")
    # env/config secrets & internal endpoints — the lead the model must
    # chase (capstone s46: API_TOKEN+API_URL sat in config.env unseen for
    # 30min while docker/nginx dead ends burned turns)
    for m in _ENV_SECRET.finditer(out):
        d["creds"].append({"user": m.group(1), "secret": m.group(2),
                           "host": None})
    for m in _ENV_URL.finditer(out):
        if len(d["findings"]) < 8:
            d["findings"].append(f"endpoint:{m.group(1)}={m.group(2)[:80]}")


_HIDDEN_TAG = re.compile(
    r"<input\b[^>]*type=['\"]hidden['\"][^>]*>", re.IGNORECASE)
_ATTR_NAME = re.compile(r"name=['\"]([\w.\[\]-]+)['\"]", re.IGNORECASE)
_ATTR_VALUE = re.compile(r"value=['\"]([^'\"]*)['\"]", re.IGNORECASE)

_PARSERS = {
    "nmap": _p_nmap,
    "masscan": _p_masscan,
    "hydra": _p_hydra,
    "medusa": _p_hydra,
    "getent": _p_getent,
}

_SKIP_TOKENS = {"sudo", "timeout", "nice", "env", "watch", "stdbuf", "time"}


def _tool_token(cmd: str) -> str:
    """First real binary name in the command — skips sudo/timeout wrappers."""
    for tok in (cmd or "").strip().split():
        name = tok.rsplit("/", 1)[-1]
        if name in _SKIP_TOKENS or "=" in tok:
            continue
        return name
    return ""


def parse_output(cmd: str, out: str) -> dict:
    """Raw output → facts delta. Never raises: garbage in, empty delta out."""
    d: dict = {"ips": set(), "names": {}, "ports": {}, "creds": [],
               "findings": [], "denials": [], "caps": [], "cap_cron": []}
    try:
        # an IP in the command line is intent, not discovery — its own error
        # output ("Failed to connect to 10.42.0.5") must not retroactively
        # whitelist it for the foreign-ip guard (self-seeding bypass)
        cmd_ips = set(_IP_RE.findall(cmd or ""))
        for ip in _IP_RE.findall(out or ""):
            if ip not in cmd_ips:
                d["ips"].add(ip)
        parser = _PARSERS.get(_tool_token(cmd))
        if parser:
            parser(out or "", d)
        _p_generic(out or "", d)
        _p_denials(cmd, out or "", d)
        _p_caps(cmd, out or "", d)
        # dedup creds — a tool parser (hydra host+login) and the generic pair
        # regex can hit the same line; keep the entry carrying a host
        seen: dict[tuple, dict] = {}
        for c in d["creds"]:
            k = (c["user"], c["secret"])
            if k not in seen or (not seen[k]["host"] and c["host"]):
                seen[k] = c
        d["creds"] = list(seen.values())
        # enum4linux-style user lists → findings note (not creds)
        for m in _ENUM_USER.finditer(out or ""):
            if len(d["findings"]) < 8:
                d["findings"].append(f"user:{m.group(1)}")
    except Exception:        # extraction must never break a turn
        log.debug("parse_output failed", exc_info=True)
    return d


def _delta_summary(d: dict) -> str:
    parts = []
    nports = sum(len(p) for p in d.get("ports", {}).values())
    if nports:
        parts.append(f"{nports} ports")
    if d.get("creds"):
        parts.append(f"{len(d['creds'])} cred{'s' if len(d['creds']) != 1 else ''}")
    if d.get("names"):
        parts.append(f"{len(d['names'])} hostnames")
    return ", ".join(parts)


@dataclass
class Percept:
    reply: str          # compact text for the tool result the model sees
    status: str = "ok"  # ok | error | no_change | busy
    facts: dict = field(default_factory=dict)


# compression bounds — the pane tail can be thousands of lines; the model
# needs the head (command context) and tail (results/errors), not the middle
_HEAD_LINES, _TAIL_LINES = 20, 8
_MAX_REPLY = 1700

# auth-loop detector: a POST to a login endpoint that returns an empty/tiny
# body is a silent 302-back-to-form — curl exits 0 so the model reads it as
# "login done" and burns turns exploiting an unauthenticated session (the
# session-39 DVWA loop). Annotate the one deterministic symptom.
_LOGIN_URL = re.compile(r"(?:/|^)(?:login|signin|auth)[\w./-]*", re.IGNORECASE)
_POST = re.compile(r"(?:\s-d\s|--data\b|POST)", re.IGNORECASE)


def _auth_note(cmd: str, stripped: str) -> str:
    if not (_POST.search(cmd) and _LOGIN_URL.search(cmd)):
        return ""
    body = stripped.strip()
    if len(body) > 400 or "login" not in body.lower() and body:
        # a real response body without a login bounce = probably fine
        return ""
    return ("\n[auth unverified — login POST returned no usable body "
            "(empty/redirect): credentials or a hidden field were rejected. "
            "Fetch the form, extract hidden inputs (user_token/csrf/_token) "
            "and include them in the POST, then VERIFY by fetching a "
            "protected page before exploiting.]")


def normalize(cmd: str, out: str, exit_code: int | None, *,
              timed_out: bool = False) -> Percept:
    """exec/type output → (compact reply, status, facts delta)."""
    stripped = strip_ansi(out or "")
    delta = parse_output(cmd, stripped)
    if exit_code is None:
        status = "busy" if timed_out else ("no_change" if not stripped.strip()
                                           else "ok")
    elif exit_code != 0:
        status = "error"
    elif not stripped.strip():
        status = "no_change"
    else:
        status = "ok"
    lines = stripped.splitlines()
    if len(lines) > _HEAD_LINES + _TAIL_LINES:
        elided = len(lines) - _HEAD_LINES - _TAIL_LINES
        hint = _delta_summary(delta)
        stripped = (
            "\n".join(lines[:_HEAD_LINES])
            + f"\n[… {elided} lines elided"
            + (f" — extracted: {hint}" if hint else "")
            + "]\n"
            + "\n".join(lines[-_TAIL_LINES:]))
    reply = stripped[:_MAX_REPLY]
    if exit_code is not None:
        reply = f"{reply}\n(exit {exit_code})" if reply else f"exit {exit_code}"
    reply += _auth_note(cmd, stripped)
    return Percept(reply=reply, status=status, facts=delta)


_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)


def parse_worker_report(text: str) -> dict | None:
    """Extract a worker's closing JSON report. Workers are asked to end
    with {"summary","findings","creds","hosts","next"}; returns the parsed
    dict or None when the report is plain prose (caller falls back to
    parse_output over the text)."""
    if not text:
        return None
    text = text.strip()
    cands = [text]
    # prose around the JSON (model wrapped it in a sentence/fence) — take
    # the largest balanced {...} span as a fallback candidate
    if not text.startswith("{"):
        m = _JSON_OBJ.search(text)
        if m:
            cands.append(m.group(0))
    for c in cands:
        try:
            d = json.loads(c)
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict) and any(
                k in d for k in ("findings", "creds", "hosts",
                                 "summary", "next")):
            return d
    return None
