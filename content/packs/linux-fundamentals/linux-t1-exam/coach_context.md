Quest: linux-t1-exam (tier 1 EXAM, linux-fundamentals)

Ground truth for the coach:
- foothold: anonymous vsftpd on :21 (anon_root=/opt/onboarding) —
  `ftp anonymous@onboarding01` → get welcome.txt → intern / Intern2024! → ssh
- privesc: /usr/bin/python3 (→ python3.11) carries SUID →
  python3 -c 'import os;os.execl("/bin/sh","sh","-p")' → root shell
- flags: /home/intern/user.txt, /root/root.txt

This is an EXAM — coaching posture is stricter than teaching quests:
- Confirm what they've already demonstrated (loot → ssh → SUID → root) and
  point at the *stage* that's missing, not the command.
- If they ask for a direct answer, redirect to the matching teaching quest
  (first-foothold for creds, suid-hunt for privesc) — the technique is
  identical, only the dressing changed.
- Nudge at the meta level first ("what did the tier teach about finding
  credentials?"), escalate to stage hints only after real time passes.

Wrong turns: brute-forcing ssh (creds are lootable, that's the point),
ignoring the ftp/http services nmap shows, trying every SUID binary instead
of checking GTFOBins per candidate.
