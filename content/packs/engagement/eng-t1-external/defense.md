# Defense notes — eng-t1-external

## What this scenario exercises

The trainee (or agent) conducts a scoped external assessment: discovery,
service enumeration, vulnerability validation, and a written report —
against real infrastructure the operator declared in-scope.

## Blue-team perspective

- **Expect noisy recon.** Masscan/rustscan and nmap -sC scripts are loud
  at the perimeter; authenticated validation steps land as normal service
  traffic. Watch for scan bursts, then follow-up connections on the same
  ports.
- **Scope boundaries matter.** A well-run engagement never touches
  adjacent addresses — out-of-scope traffic from the testing host is a
  process failure worth flagging to the tester, not just an alert.
- **Candidates vs confirmed.** Scanner output that never gets validated
  is noise for both sides; the report's "ruled out" section is where a
  good tester saves the defender real follow-up work.
- **Evidence quality.** A confirmed finding should carry reproducible
  proof (banner, response, access) — that is what makes remediation
  actionable instead of a re-scan request.
