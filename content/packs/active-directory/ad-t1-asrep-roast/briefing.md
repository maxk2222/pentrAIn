# No Preauth

> **Track**: Active Directory · **Tier**: 1 · **Estimated time**: ~35 min

## Scenario

`corp.pentrain.local` still carries a legacy service account from before
Kerberos preauthentication was enforced. For that account, the KDC hands
an encrypted AS-REP to *anyone who asks* — no credentials required. Your
job is to find it, roast it, and cash out.

## Objectives

1. Enumerate domain users — you have no credentials, so use the channels
   that don't need any.
2. Request AS-REPs for every candidate, crack the offline hash.
3. Find the roasted account's loot channel and take the flag.

## Environment

- **Kali**: your attack workstation
- **dc01**: Windows Server 2022, domain controller for `corp.pentrain.local`

> Note: first AD deploy takes a while — Windows template + domain promotion.

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `pentrAIn{...}` — submit them in the Flags panel.
