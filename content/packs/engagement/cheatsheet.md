# Engagement track reference

External engagements run against operator-declared scope — there are no
planted targets and no lab safety net beyond the rules of engagement.

## Methodology

1. **Authorize** — the scope snapshot (nets/hosts/ports + authorization
   line) is the contract; everything outside it is denied in code.
2. **Recon** — broad discovery over the authorized nets; live hosts drive
   everything downstream.
3. **Enumerate** — services, versions, banners, config surface per host.
4. **Assess** — vulnerability checks and config review per surface; every
   suspected issue is a tracked candidate.
5. **Validate** — reproduce candidates with direct evidence before they
   count; unprovable ones are ruled out with the reason recorded.
6. **Report** — findings grouped by validation state, coverage summary,
   remediation guidance.

## Rules of engagement

- Read-only posture: enumerate, probe, validate. No destructive actions,
  no DoS, no persistence, no data exfiltration — proof-of-access evidence
  is the standard.
- Scope is a hard whitelist. Discovered-but-out-of-scope items are
  evidence for the report's "adjacent surface" note, never a target.
- Keep fingerprints gentle on real infrastructure: default rates, no
  aggressive timing templates, serial over parallel where unsure.
