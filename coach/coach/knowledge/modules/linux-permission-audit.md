---
id: linux-permission-audit
title: Linux permission review — capabilities and service identities
triggers: [getcap, capability, cap_setuid, cap_dac_read_search, service identity]
---

## Read-only review

1. Compare the collected capability inventory with an approved baseline.
2. Confirm which service identity owns each executable and which files it needs.
3. Treat an unexpected capability as a finding to investigate, not as proof of use.
4. Recommend removing unnecessary privileges or replacing them with narrow file ownership.
5. Verify intended work still succeeds and unrelated administrative access remains denied.

## Evidence and remediation

Record the executable, owner, observed permission, expected purpose and
change owner. Re-check the inventory after deployment and alert on unexpected
changes. Do not attempt to use the privilege to access unrelated files.
