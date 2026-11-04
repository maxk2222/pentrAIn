# Scoped: First External Engagement

This is not a lab. You are running an **authorized penetration test**
against real targets that exist outside the training range.

## Before anything works

Open the **scope dialog** (Shield icon in the session toolbar) and declare
the engagement whitelist:

- **Authorization** — the written reference for who authorized this test
  (contract, ticket, scope letter). Required; it becomes part of the ROE
  audit trail.
- **Nets** — the authorized CIDRs/IPs, one per line.
- **Hosts** — authorized domains; their current DNS records are pinned at
  authorization time.
- **URLs / Ports** — optional: pre-authorized URL surface and a port
  whitelist for the rules of engagement.

Until the scope is locked, the agent denies **every** target — an
undeclared whitelist means no engagement exists.

## The engagement

With scope locked, turn autonomy to **Takeover (L4)** and let the agent
run the full methodology:

1. **Recon** — discovery sweeps over the authorized nets/hosts.
2. **Enumerate** — service/version detail per live surface.
3. **Assess** — vulnerability and configuration checks; every suspected
   issue becomes a tracked candidate.
4. **Validate** — candidates are reproduced with direct evidence before
   they count as confirmed findings; dead ends get marked ruled-out.
5. **Report** — findings, coverage and remediation assembled into
   `engagement-report.md`.

Watch it work in the Kali pane; the Findings tab shows the typed finding
list as it builds, and the Report tab renders the assembled deliverable.

## Scoring

The `report` flag checks the written `engagement-report.md` — scope
header, real hosts/services, findings (with validation states) and
recommendations must all be present.
