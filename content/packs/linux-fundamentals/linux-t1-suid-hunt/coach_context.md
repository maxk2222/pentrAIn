Quest: linux-t1-suid-hunt (tier 1, linux-fundamentals)

Ground truth for the coach:
- foothold: python http drop on :80 autoindexes /opt/onboarding →
  login-credentials.txt leaks trainee / Start123! → ssh
- privesc: /usr/bin/base64 has the setuid bit → GTFOBins file-read:
  `base64 /root/root.txt | base64 -d` — no interactive shell needed
- decoy: /usr/local/bin/sysdiag is also SUID but just prints fake diagnostics —
  a deliberate "not every SUID is exploitable" lesson
- flags: /home/trainee/user.txt, /root/root.txt

Intended path:
nmap → http :80 → login-credentials.txt → ssh trainee@ → `find / -perm
-4000 -type f` → identify base64 in the list → GTFOBins → read root.txt
directly

Common wrong turns:
- running sysdiag expecting a shell — it does nothing; pivot them to *which*
  SUIDs can read files
- trying sudo -l — trainee has no sudo rights; SUID is the path
- brute-forcing SSH — the creds are free on the onboarding web share

Style: tier 1 — teach the find -perm + GTFOBins workflow, it's reusable for
the rest of the track.
