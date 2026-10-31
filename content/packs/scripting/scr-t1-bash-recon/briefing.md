# Recon.sh

**Situation.** The ops team stood up `filesrv01` overnight — an internal
fileserver nobody has audited yet. Your task is not to attack it by hand but
to *script* the first pass: everything a pentester does in the first ten
minutes, captured in a reusable bash script.

**Your job**

1. Write `/root/recon.sh` on your Kali — it must probe the target and print
   the open service ports it finds (there is a web service on an unusual
   port — catch it). **The grader runs it with no arguments** — bake the
   target in: `filesrv01` resolves by name inside the range.
2. The target's SSH log is full of failed logins. Extract the brute-forcing
   source IP and write it, one IP per line, to `/root/attackers.txt`.

**Environment.** One target VM (`filesrv01`), reachable directly from your
Kali console — range hostnames resolve, no IP guessing needed.
Anonymous FTP is said to carry a host inventory — worth a look for context.

**Why this matters.** Recon by hand doesn't scale to a 200-host engagement.
A script you trust turns ten minutes into ten seconds — and this one is
graded on its output, not your process.

Difficulty: easy · Track: Scripting & Automation
