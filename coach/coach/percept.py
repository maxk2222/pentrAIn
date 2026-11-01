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
               "findings": []}
    try:
        for ip in _IP_RE.findall(out or ""):
            d["ips"].add(ip)
        parser = _PARSERS.get(_tool_token(cmd))
        if parser:
            parser(out or "", d)
        _p_generic(out or "", d)
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
