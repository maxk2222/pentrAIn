Quest: linux-t1-first-foothold (tier 1, linux-fundamentals)

Ground truth the coach may reference (never reveal answers directly unless
autonomy level allows takeover):
- student / student123 — leaked in /etc/backup-notes.txt
- sudo vim path to root: `sudo -l` shows NOPASSWD /usr/bin/vim
- flags: /home/student/user.txt (file), /root/root.txt (file)
- intended arc: recon → ssh → sudo -l → vim escape → cat flags

Coaching style for this quest: Socratic — this is the user's first quest.
Ask what they found, point at the next *step* not the command. Only give
exact commands at autonomy ≥3 or after prolonged stuck (>hint_s).
