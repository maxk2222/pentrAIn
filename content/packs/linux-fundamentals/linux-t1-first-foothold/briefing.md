# First Foothold

A junior sysadmin left a Debian server (`target01`, 10.x.10.21) exposed on the
training range. Rumor says credentials float around in plain sight and sudo
rights were granted carelessly.

## Objectives

1. Recon the host — find open services.
2. Get a shell as the `student` user.
3. Escalate to `root`.
4. Submit both flags: `/home/student/user.txt` and `/root/root.txt`.

## Getting started

Your Kali desktop is already on the same network. The target answers on the
range subnet — discover it with `nmap` or just read the machine's notes; the
admin was not careful about what ends up in `/etc`.

## Ground rules

- Everything inside the range is fair game.
- Do not attack the range router or the platform itself.
- The coach watches your commands — ask it when stuck.
