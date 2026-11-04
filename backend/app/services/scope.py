"""Engagement scope normalization — the ROE snapshot stored on the session.

An operator declares what the agent MAY touch (nets, hosts, urls, ports)
plus a written authorization line. We normalize it once, resolve hostnames
server-side (the resolved IPs are pinned as /32 nets so DNS drift can't
smuggle a different target past the coach's literal-IP guard), and hand
the coach a single locked whitelist via session_context → ctx["scope"].
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

MAX_ITEMS = 32
_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}$")


class ScopeError(Exception):
    """Validation failure surfaced as HTTP 422."""


def _norm_nets(raw: list[str]) -> list[str]:
    nets: list[str] = []
    for c in raw or []:
        try:
            net = ipaddress.ip_network(str(c).strip(), strict=False)
        except ValueError:
            raise ScopeError(f"invalid CIDR/net: {c!r}")
        if net.is_loopback or net.is_link_local or net.is_multicast:
            raise ScopeError(f"not a usable target net: {c}")
        s = str(net)
        if s not in nets:
            nets.append(s)
    if len(nets) > MAX_ITEMS:
        raise ScopeError(f"too many nets (>{MAX_ITEMS})")
    return nets


def _norm_hosts(raw: list[str]) -> list[str]:
    hosts: list[str] = []
    for h in raw or []:
        h = str(h).strip().lower().rstrip(".")
        try:
            ipaddress.ip_address(h)          # IP literal → goes to nets
            continue
        except ValueError:
            pass
        if not _HOST_RE.match(h) or len(h) > 253:
            raise ScopeError(f"invalid hostname: {h!r}")
        if h not in hosts:
            hosts.append(h)
    if len(hosts) > MAX_ITEMS:
        raise ScopeError(f"too many hosts (>{MAX_ITEMS})")
    return hosts


def _norm_ports(raw: list) -> list[int]:
    ports: list[int] = []
    for p in raw or []:
        try:
            p = int(p)
        except (TypeError, ValueError):
            raise ScopeError(f"invalid port: {p!r}")
        if not (1 <= p <= 65535):
            raise ScopeError(f"port out of range: {p}")
        if p not in ports:
            ports.append(p)
    if len(ports) > MAX_ITEMS:
        raise ScopeError(f"too many ports (>{MAX_ITEMS})")
    return sorted(ports)


async def _resolve(host: str) -> list[str]:
    """Server-side A/AAAA lookup — records WHERE an authorized name pointed
    at authorization time. Uses the event loop's getaddrinfo (non-blocking)."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, None, family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return []
    out: list[str] = []
    for fam, *_rest, sockaddr in ((i[0], i[4]) for i in infos):
        if fam == socket.AF_INET:
            ip = sockaddr[0]
            if ip not in out:
                out.append(ip)
    return out


async def normalize(body) -> dict:
    """ScopeIn → canonical scope dict (the value stored in scope_json)."""
    auth = (body.authorization or "").strip()
    if len(auth) < 8:
        raise ScopeError(
            "authorization line required — state who authorized this "
            "engagement (e.g. 'ACME contract #123, valid until 2026-12')")

    nets = _norm_nets(body.nets)
    hosts = _norm_hosts(body.hosts)
    ports = _norm_ports(body.ports)

    # urls are sugar: their authority contributes hosts (or /32 nets for
    # IP literals) and an explicit port joins the port whitelist
    for u in body.urls or []:
        u = str(u).strip()
        p = urlparse(u if "://" in u else f"https://{u}")
        if not p.hostname:
            raise ScopeError(f"invalid url: {u!r}")
        h = p.hostname.lower().rstrip(".")
        try:
            ipaddress.ip_address(h)
            net = str(ipaddress.ip_network(f"{h}/32", strict=False))
            if net not in nets:
                nets.append(net)
        except ValueError:
            if not _HOST_RE.match(h):
                raise ScopeError(f"invalid url host: {h!r}")
            if h not in hosts:
                hosts.append(h)
        if p.port is not None and p.port not in ports:
            ports = sorted(ports + [p.port])

    # pin every authorized hostname's current A records as /32 nets —
    # the coach's literal-IP guard then ALSO covers what DNS resolves to,
    # and the resolved map is the audit trail of where names pointed
    resolved: dict[str, list[str]] = {}
    for h in hosts:
        ips = await _resolve(h)
        if ips:
            resolved[h] = ips
            for ip in ips:
                n32 = str(ipaddress.ip_network(f"{ip}/32", strict=False))
                if n32 not in nets:
                    nets.append(n32)

    if not nets and not hosts:
        raise ScopeError("empty scope — declare at least one net or host")

    return {
        "version": 1, "locked": True, "mode": "external-engagement",
        "authorized_by": auth[:300],
        "authorized_at": datetime.now(timezone.utc).isoformat(),
        "nets": nets, "hosts": hosts, "ports": ports,
        "resolved": resolved,
        "unresolved": [h for h in hosts if h not in resolved],
    }
