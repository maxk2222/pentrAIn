#!/usr/bin/env python3
"""Refresh coach/knowledge/refs/ from upstream technique references.

Vendored excerpts give `search_technique` (source=vendored) an offline
baseline — the agent gets HackTricks/PayloadsAllTheThings-grade answers
in labs with no internet. Run this on a maintainer machine with network:

    scripts/sync_tech_refs.py            # refresh all
    scripts/sync_tech_refs.py --check    # list files, no fetch

Every vendored file gets an attribution header (source repo + upstream
path + sync date) — upstream licenses are preserved by keeping the
headers and listing sources here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REFS = REPO / "coach" / "coach" / "knowledge" / "refs"

_RAW = "https://raw.githubusercontent.com"

# (dest name, upstream repo, path-in-repo) — keep dests short and
# grep-friendly (they show up as `name:line` in search_technique hits).
MANIFEST: list[tuple[str, str, str]] = [
    # ---- PayloadsAllTheThings (MIT) — attack-method checklists ----
    ("patt-sqli.md", "swisskyrepo/PayloadsAllTheThings",
     "SQL Injection/README.md"),
    ("patt-xss.md", "swisskyrepo/PayloadsAllTheThings",
     "XSS Injection/README.md"),
    ("patt-ssrf.md", "swisskyrepo/PayloadsAllTheThings",
     "Server Side Request Forgery/README.md"),
    ("patt-ssti.md", "swisskyrepo/PayloadsAllTheThings",
     "Server Side Template Injection/README.md"),
    ("patt-lfi.md", "swisskyrepo/PayloadsAllTheThings",
     "File Inclusion/README.md"),
    ("patt-upload.md", "swisskyrepo/PayloadsAllTheThings",
     "Upload Insecure Files/README.md"),
    ("patt-cmdi.md", "swisskyrepo/PayloadsAllTheThings",
     "Command Injection/README.md"),
    ("patt-xxe.md", "swisskyrepo/PayloadsAllTheThings",
     "XXE Injection/README.md"),
    ("patt-jwt.md", "swisskyrepo/PayloadsAllTheThings",
     "JSON Web Token/README.md"),
    ("patt-graphql.md", "swisskyrepo/PayloadsAllTheThings",
     "GraphQL Injection/README.md"),
    ("patt-ldap.md", "swisskyrepo/PayloadsAllTheThings",
     "LDAP Injection/README.md"),
    ("patt-deser.md", "swisskyrepo/PayloadsAllTheThings",
     "Insecure Deserialization/README.md"),
    ("patt-ad.md", "swisskyrepo/PayloadsAllTheThings",
     "Methodology and Resources/Active Directory Attack.md"),
    ("patt-cors.md", "swisskyrepo/PayloadsAllTheThings",
     "CORS Misconfiguration/README.md"),
    ("patt-csrf.md", "swisskyrepo/PayloadsAllTheThings",
     "Cross-Site Request Forgery/README.md"),
    ("patt-redirect.md", "swisskyrepo/PayloadsAllTheThings",
     "Open Redirect/README.md"),
    ("patt-revshell.md", "swisskyrepo/PayloadsAllTheThings",
     "Methodology and Resources/Reverse Shell Cheatsheet.md"),
    ("patt-privesc-lin.md", "swisskyrepo/PayloadsAllTheThings",
     "Methodology and Resources/Linux - Privilege Escalation.md"),
    ("patt-privesc-win.md", "swisskyrepo/PayloadsAllTheThings",
     "Methodology and Resources/Windows - Privilege Escalation.md"),
    ("patt-pivot.md", "swisskyrepo/PayloadsAllTheThings",
     "Methodology and Resources/Network Pivoting Techniques.md"),
    ("patt-nosql.md", "swisskyrepo/PayloadsAllTheThings",
     "NoSQL Injection/README.md"),
    ("patt-oauth.md", "swisskyrepo/PayloadsAllTheThings",
     "OAuth Misconfiguration/README.md"),
    ("patt-saml.md", "swisskyrepo/PayloadsAllTheThings",
     "SAML Injection/README.md"),
    ("patt-proto-pollution.md", "swisskyrepo/PayloadsAllTheThings",
     "Prototype Pollution/README.md"),
    ("patt-race.md", "swisskyrepo/PayloadsAllTheThings",
     "Race Condition/README.md"),
    ("patt-web-cache.md", "swisskyrepo/PayloadsAllTheThings",
     "Web Cache Deception/README.md"),
    # ---- GTFOBins (GPL) — unix binaries → shells/privesc; NOTE: the
    # _gtfobins files carry NO .md extension upstream
    ("gtfobins-nmap.md", "GTFOBins/GTFOBins.github.io",
     "_gtfobins/nmap"),
    ("gtfobins-find.md", "GTFOBins/GTFOBins.github.io",
     "_gtfobins/find"),
    ("gtfobins-tar.md", "GTFOBins/GTFOBins.github.io",
     "_gtfobins/tar"),
    ("gtfobins-vim.md", "GTFOBins/GTFOBins.github.io",
     "_gtfobins/vim"),
    ("gtfobins-bash.md", "GTFOBins/GTFOBins.github.io",
     "_gtfobins/bash"),
    ("gtfobins-python.md", "GTFOBins/GTFOBins.github.io",
     "_gtfobins/python"),
    ("gtfobins-awk.md", "GTFOBins/GTFOBins.github.io",
     "_gtfobins/awk"),
    # ---- HackTricks (CC) — broad methodology ----
    ("ht-ad-kerberoast.md", "HackTricks-wiki/hacktricks",
     "src/windows-hardening/active-directory-methodology/kerberoast.md"),
    ("ht-ad-readme.md", "HackTricks-wiki/hacktricks",
     "src/windows-hardening/active-directory-methodology/README.md"),
    ("ht-privesc-lin.md", "HackTricks-wiki/hacktricks",
     "src/linux-hardening/linux-basics/linux-privilege-escalation/README.md"),
    ("ht-privesc-win.md", "HackTricks-wiki/hacktricks",
     "src/windows-hardening/windows-local-privilege-escalation/README.md"),
    ("ht-web-cmdi.md", "HackTricks-wiki/hacktricks",
     "src/pentesting-web/command-injection.md"),
]


def _fetch(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "pentrain-sync/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="list manifest dests + local state, fetch nothing")
    ap.add_argument("--force", action="store_true",
                    help="re-download files that already exist")
    args = ap.parse_args()
    if args.check:
        for dest, repo, path in MANIFEST:
            mark = "local" if (REFS / dest).exists() else "missing"
            print(f"{mark:7s} {dest}  <- {repo}/{path}")
        return 0

    REFS.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    ok = fail = 0
    for dest, repo, path in MANIFEST:
        if (REFS / dest).exists() and not args.force:
            print(f"skip  {dest} (exists — --force to refresh)")
            ok += 1
            continue
        url = f"{_RAW}/{repo}/master/{urllib.request.quote(path)}"
        try:
            body = _fetch(url)
        except (urllib.error.URLError, TimeoutError):
            # try main branch — repos drift between master/main
            url = f"{_RAW}/{repo}/main/{urllib.request.quote(path)}"
            try:
                body = _fetch(url)
            except (urllib.error.URLError, TimeoutError) as e2:
                print(f"FAIL  {dest}: {e2}")
                fail += 1
                continue
        header = (f"<!-- vendored from https://github.com/{repo}"
                  f"/blob/master/{path} — synced {today} "
                  f"(scripts/sync_tech_refs.py) -->\n\n")
        (REFS / dest).write_text(header + body, encoding="utf-8")
        print(f"ok    {dest} ({len(body) // 1024}K)")
        ok += 1
    print(f"\n{ok} synced, {fail} failed → {REFS}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
