# Sticky Bits

`suid01` is an onboarding VM for new starters. Security posture: "we'll fix it
later." Someone left the credentials in plain sight — and a sysadmin decided
that diagnostic tools should run "elevated" via the setuid bit.

## Objectives

1. Find the way in — the last admin left notes behind.
2. Read the user flag.
3. Escalate to `root` and read the root flag.

## Suggested flow

- Loot what the filesystem offers before touching a wordlist.
- Once inside: what runs as root that shouldn't?
- Not every setuid binary is a door — figure out which one actually is.

## Environment

- **Kali**: your attack workstation
- **suid01**: the onboarding VM on the range LAN
