# Wildcard

`cron01` belongs to the ops team. Their backup policy is aggressive — a root
cronjob packs `/home/ops/backup` every single minute — and their notes are a
little too honest about what goes wrong with it.

## Objectives

1. Find the credentials the ops team left lying around.
2. Get a shell as `ops` and read the user flag.
3. Abuse the scheduled archiving job to reach `root`.

## Suggested flow

- Loot what the host shares — the backup policy is published on an open share.
- Watch what runs on a schedule as root, and *where* it operates.
- Wildcards in privileged commands trust filenames completely. Filenames are
  yours to choose.

## Environment

- **Kali**: your attack workstation
- **cron01**: the ops team's backup host on the range LAN
