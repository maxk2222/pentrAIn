# Blind Pipe

> **Track**: Scripting & Automation · **Tier**: 3 · **Estimated time**: ~30 min

## Scenario

`web01` runs a legacy diagnostics CGI: give it an interface name, it
runs `ip -brief addr show <name>` and echoes the result. The parameter
reaches the shell unquoted — a classic command-injection sink. Poking it
by hand is easy; the quest is to *automate* it.

## Deliverables

1. `/root/inject.py` — a python script that drives the endpoint: builds
   the payload, sends it, parses the command output.
2. `/root/loot.txt` — the flag the script exfiltrated from the operator's
   home directory.
3. Submit the loot flag.

## Environment

- **Kali**: your workstation — requests/paramiko standard
- **web01**: apache + the vulnerable CGI on :80

**This is a scripting quest** — the grader checks the script and its
output, not your browser history.
