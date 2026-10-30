# Exam: Supply Chain

T3 assessment for the linux-fundamentals track. Three tiers deep:
a bastion anyone can reach, an app box only the bastion can reach, and a
database only the app box can reach. Credentials leak at every stage —
your job is to keep moving.

## Objectives

1. Foothold on `bastion01` — the box advertises its account.
2. Pivot to `app01`, escalate, collect its flag.
3. Pivot again to `db01` and take the final flag.

## Rules of engagement

- Three flags, one per host.
- Every hop's credentials exist on the previous hop — loot everything.
- `ssh -J` chains jumps cleanly; learn the syntax once, use it twice.

## Environment

- **Kali**: your attack workstation
- **bastion01** → **app01** → **db01**: the tiered network
