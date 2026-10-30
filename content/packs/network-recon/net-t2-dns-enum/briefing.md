# Zone Out

`dns01` is the corp nameserver — and apparently also a file drop, an SNMP
beacon, and an SSH box. The admin philosophy was "it's internal, who cares."

## Objectives

1. Pull every name the DNS knows — without guessing a single one.
2. Collect the file that's served without authentication.
3. Turn service-level enumeration into an account, then a shell.

## Suggested flow

- This box is mostly UDP. Scan UDP explicitly or you'll see half the story.
- Ask the nameserver for the whole zone — misconfigured ones just hand it over.
- SNMP in factory state tells you *who*; a wordlist tells you *how*.

## Environment

- **Kali**: your attack workstation
- **dns01**: the corp nameserver on the range LAN
