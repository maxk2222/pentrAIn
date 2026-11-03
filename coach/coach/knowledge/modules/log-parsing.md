---
id: log-parsing
title: Log analysis field traps — column drift, marker anchoring, validation
triggers: [awk, journalctl, auth.log, access.log, Failed password, uniq -c, top talker]
---

# Log analysis field traps

- sshd `Failed password for <user> from <ip>`: "invalid user" lines insert
  TWO fields (`for invalid user nagios from …`) — a fixed `awk '{print $11}'`
  silently counts the wrong column (s54: counted 192.0.2.99 instead of the
  real top attacker 203.0.113.44). ALWAYS extract by marker:
  `grep -oP 'from \K[0-9.]+'`. Same trap for `Accepted password`, Apache,
  sudo — anchor on the keyword, never the column number.
- Validate a parser on a SAMPLE line first (`… | head -3`), then on counts
  (`| sort | uniq -c | sort -rn | head`) — and reuse the exact pipeline
  you validated in the deliverable script; don't re-derive it.
