# Exam: Three Doors Down

T3 assessment for the network-recon track. A perimeter nameserver that
can't stop talking, a public docs host with indiscreet notes, and a vault
that accepts only dmz-originated traffic.

## Objectives

1. Enumerate the edge's UDP services — get the first foothold for free.
2. Loot the dmz's public docs — one flag and the keys to everything else.
3. Chain two pivots into the vault and take the final flag.

## Rules of engagement

- Three flags, one per host.
- Everything required was taught this tier: UDP enum, zone transfers,
  SNMP leaks, ProxyJump chains.

## Environment

- **Kali**: your attack workstation
- **edge01** → **dmz01** → **vault01**: three trust boundaries
