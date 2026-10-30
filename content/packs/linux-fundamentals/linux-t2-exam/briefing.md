# Exam: The Maintenance Window

T2 assessment for the linux-fundamentals track. The ops team keeps a
contractor account on `maint01` — and two different ways to accidentally
become root. Grade A if you find both, pass if you find one.

## Objectives

1. Get onto `maint01` with the credentials the box itself advertises.
2. Collect the user flag.
3. Escalate to root — via the scoped sudo right, the trusting cronjob,
   or both.

## Rules of engagement

- Two flags: user and root. Both privesc paths were taught this tier.
- The wildcard-cron path has a ~60s cycle time — patience is a skill too.

## Environment

- **Kali**: your attack workstation
- **maint01**: the assessment target on the range LAN
