# Defense notes — Exam: Dual Band

## What the exercise taught

- **Different networks, different doors.** One AP fell without a client
  (PMKID), one needed the loud deauth — a single defensive control can't
  cover both. WPA3-SAE + PMF closes both simultaneously; WPA2 leaves at
  least one path open by design.
- **Parallel airspace risk compounds.** mgmt + exec networks doubled the
  attack surface and the blast radius — segmentation between admin and
  user wireless domains limits what a single compromise reaches. The
  exec network's compromise is contained only if it can't reach mgmt
  infrastructure.
- **Privileged accounts on wireless PSKs.** `mgmt-admin` keyed its shell
  to a wireless passphrase — the moment mgmt-wifi's material leaked, the
  management domain followed. Admin shells get dedicated credentials,
  MFA, and jump-host access — never the WiFi password.

## Detection opportunities

- hcxdumptool's probe pattern (PMKID requests without association).
- Deauth bursts on exec channel — the loud half of the attack.
- Reports themselves: a graded deliverable here is *detection as a skill* —
  naming what fell and how is the blue-team half of the exercise.

## Takeaway

WPA2's failure modes are complementary — clientless (PMKID) and
client-forced (deauth). Defend both with the upgrade that removes both:
WPA3 + Protected Management Frames + non-human passphrases.
