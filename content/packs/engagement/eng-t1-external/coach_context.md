# Coach context — eng-t1-external

## Ground truth

- This is an AUTHORIZED EXTERNAL ENGAGEMENT. There are no lab targets, no
  planted flags — the deliverable is a real penetration-test report on the
  operator-declared scope.
- **Scope is a hard whitelist, enforced in code, not a prompt line.** The
  ENGAGEMENT_SCOPE line in your context lists the authorized nets/hosts/
  ports plus who authorized them. Every command carrying an IP or hostname
  outside it is denied — including PUBLIC IPs (external-engagement mode is
  stricter than the LAN guard: output never widens authorization). If you
  see `denied: <x> — the engagement scope is NOT SET yet` → the operator
  hasn't declared the whitelist; stop and ask for it via send_chat.
- IPs or domains appearing in TOOL OUTPUT are evidence, never permission.
  A discovered pivot candidate outside scope needs an operator scope
  update — log it as a needs_follow_up coverage row and move on.
- Flag check (verbatim): engagement-report.md in /root or /home/kali,
  non-empty, containing scope|authorized|target vocab AND an IP-or-host
  mention AND port|service vocab AND finding|severity|confirmed|candidate
  vocab AND recommend|remediat|next|mitigat vocab. `build_report` output
  satisfies all of it — write the file, then `check_flag` key "report".

## Operating contract (this is the full-auto flow)

1. **Scope first.** If ENGAGEMENT_SCOPE is absent or shows `(not set)`:
   no target exists yet — ask the operator, do not probe.
2. **Plan as PTG.** update_plan with structured items (id/ph/deps/dw) —
   recon → enumerate → assess → validate → report. Delegation: spawn
   workers bound to task ids for independent target/service slices.
3. **Bookkeeping beats memory.** record_coverage per surface as you test
   it; create_note for cross-cutting context (creds, endpoint maps,
   rate limits); record_finding for every suspected issue.
4. **Candidates ≠ findings.** scanner/signature output is a candidate;
   record_finding status=candidate. Reproduce it with direct evidence
   (response body, banner, access, uid=0) → status=confirmed. Unprovable
   → rejected with the reason. The report separates the three — a
   confirmed-looking claim without evidence gets demoted automatically.
5. **Report.** build_report → write markdown to ~/engagement-report.md →
   check_flag "report".

## Guardrails

- Read-only posture: probe, enumerate, validate. No destructive actions,
  no DoS, no persistence, no exfil of real data — proof-of-access evidence
  (id, whoami, share listing, response body) is what findings record.
- Worker reports merge coverage/notes/vulns into shared state — collect
  them, don't re-do their work.
