# Open Shares

`smb01` is the office file server. IT swears the guest share is "temporary" —
it's been up for eight months, and people keep dropping things on it that don't
belong there.

## Objectives

1. Enumerate `smb01` — which services answer, which of them talk to strangers?
2. Collect the flag sitting on the open share.
3. Work your way into the restricted share.
4. Get a shell and read the user's flag.

## Suggested flow

- Map the TCP *and* UDP surface — not everything interesting listens on TCP.
- Anonymous share first; whatever you find there, assume it opens other doors.
- Credentials have a habit of working in more than one place — try them everywhere.

## Environment

- **Kali**: your attack workstation (desktop in the browser)
- **smb01**: file server on the range LAN
