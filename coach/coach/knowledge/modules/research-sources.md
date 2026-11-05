---
id: research-sources
title: Security research — which tool, which source
triggers: [searchsploit, exploit-db, cve, nvd, kev, rss, research, writeup]
---

## Pick the right research tool

- **`search_exploitdb`** — FIRST for "is there a public exploit for
  <product> <version>". Works fully offline; returns EDB ids + local
  paths under `/usr/share/exploitdb/` — `exec_in_kali cat <path>` or
  `searchsploit -m <id>` to copy.
- **`search_technique`** — for "how do I attack X". `vendored` (always),
  `kali` (deep /opt/research clones), named sites online. auto walks all.
- **`query_vuln_db`** — "does a CVE exist / what does CVE-X mean" → CVSS,
  CWE, references; [KEV] marks exploited-in-the-wild. Internet only.
- **`rss_feed`** — "what is new" (exploitdb/packetstorm drops, advisories).
  Internet only; `rss_feed list` shows the map.
- `web_search`/`web_fetch` — generic fallback for anything the four above
  miss (vendor advisories, niche error strings, non-indexed blogs).

## Canonical references (web_fetch targets when online)

| need | url |
|---|---|
| technique wiki | book.hacktricks.xyz |
| attack checklists | github.com/swisskyrepo/PayloadsAllTheThings |
| privesc binaries (linux) | gtfobins.github.io |
| privesc binaries (win) | lolbas-project.github.io |
| AD commands | wadcoms.github.io |
| shells | revshells.com |
| CVE record | nvd.nist.gov/vuln/detail/CVE-XXXX-YYYY |
| exploited-in-wild | cisa.gov/known-exploited-vulnerabilities-catalog |
| public exploits | exploit-db.com (search via search_exploitdb!) |
| OWASP cheatsheets | cheatsheetseries.owasp.org |

Offline rule: exploit lookup = search_exploitdb, technique =
search_technique vendored→kali. Never burn turns hand-guessing URLs.
