# Lateral Pressure

> **Track**: Active Directory · **Tier**: 2 · **Estimated time**: ~65 min

## Scenario

`corp.pentrain.local` grew: a linux file server everyone trusts, a
domain-joined workstation, and the DC. The file server holds what shouldn't
be there — follow the credentials as they escalate host to host until the
domain falls.

## Objectives

1. Raid the file server → `files-flag` + the first credential set
2. Land on the workstation → `ws-flag` + the second
3. Own the DC → `dc-flag`

## Environment

- **Kali**: your attack workstation
- **files01**: Debian, guest-readable SMB
- **ws01**: Windows 11, domain-joined
- **dc01**: Windows Server 2022, DC for `corp.pentrain.local`

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `pentrAIn{...}` — submit them in the Flags panel.
