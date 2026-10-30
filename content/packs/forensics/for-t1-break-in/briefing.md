# The Break-In

> **Track**: Forensics · **Tier**: 1 · **Estimated time**: ~25 min

## Scenario

The nightly integrity check flagged `evidence01`: someone got in. You have
the host — the attacker is gone, but they left the session, the stash, and
the persistence they installed. Reconstruct what happened and recover both
flags they planted.

## Objectives

1. Trace the intrusion in the auth logs — when, from where, which account
2. Follow the attacker's shell history to their stash (`stash-flag`)
3. Find and prove the persistence mechanism (`persistence-flag`)

## Environment

- **Kali**: your analysis workstation — SSH into `evidence01` as
  `analyst / analysis` (read-only account; sudo for reading logs is allowed)
- **evidence01**: the compromised host, frozen as the attacker left it

## Rules of engagement

- This is a *blue* quest: collect evidence, don't attack the box.
- Flags look like `PenTrAIn{...}` — submit them in the Flags panel.
