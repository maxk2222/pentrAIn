# Exam: Zero-Touch Vault

**Tier-3 capstone — Scripting & Automation.** Final scenario, full chain:
`web01` exposes a network-diagnostics CGI; `db01` accepts SSH only from
web01. Prove the whole compromise replayably: one script, no hands.

**Deliverables**

1. Turn the diagnostics endpoint on `web01` into code execution.
2. Recover the vault credentials stored on web01.
3. From web01, reach `db01` and write `pwned-by-script` to
   `/home/vaultadm/.pwned`.
4. Pull `/home/vaultadm/vault.txt` back and submit it.

Kali cannot reach db01 directly — the firewall only trusts web01. Your
script must route the entire hop through the compromised edge.

**This is an exam.** Solve every tier-3 scripting quest first.

Difficulty: hard · Track: Scripting & Automation
