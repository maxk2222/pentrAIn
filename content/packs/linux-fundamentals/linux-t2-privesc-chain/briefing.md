# Privilege Chains

`server01` runs a departmental backup service. The ops team leaves recovery
notes lying around — and their idea of "least privilege" is generous.

## Objectives

1. Enumerate the host — find what was left behind.
2. Obtain an `ops` shell.
3. Reach `root` — there are at least two independent routes.
4. Submit `/home/ops/user.txt` and `/root/root.txt`.

## Suggested flow

- Enumerate every service — the ops team shares recovery notes a little too openly.
- `sudo -l` on the target reveals what `ops` may run.
- A scheduled task runs every couple of minutes — check who can modify what it runs.

Bonus exercise: privesc via both the sudo path **and** the cron path.
