---
id: pivoting
title: Pivoting & multi-hop SSH — reaching filtered/internal hosts
triggers: [filtered, unreachable, pivot, ProxyCommand, ssh -J, all ports filtered]
---

# Pivoting & multi-hop ssh

A host that is alive (ping/routed) but shows EVERY port filtered = ACL or
tier isolation — it is reached by pivoting through a compromised machine,
never by more nmap variants from the same vantage.

## Multi-hop with different creds per hop

`sshpass -p PW ssh -J hop1 user@dest` only feeds ONE password — when the
hops have different creds the first prompt eats it and the second hangs.
Nest per-hop:

```bash
sshpass -p PW2 ssh \
  -o "ProxyCommand sshpass -p PW1 ssh -o StrictHostKeyChecking=no -W %h:%p u1@hop1" \
  u2@dest 'cmd'
```

- Name resolution on the forwarded hop happens on the JUMP host, not on
  Kali — `ssh … u2@db01` fails `Name or service not known` even when
  Kali's getent resolves db01. Use the destination IP instead.
- Middle boxes rarely have sshpass/expect — never assume the pivot host
  can script the second hop; drive both hops from Kali.
- Docker-internal IPs (172.16.0.0/12) are NOT reachable from Kali —
  reach them through the container host:
  `sshpass … ssh deploy@host 'curl -s http://172.x.y.z:port/'`.

## Choosing the path

Check FACTS for `valid:` creds and `blocked:` denials first — a cred
scoped to a host you can already ssh to IS the pivot path. `blocked:
filtered:<ip>@<vantage>` entries name exactly which vantage can NOT
reach a host; route around them instead of re-proving them.
