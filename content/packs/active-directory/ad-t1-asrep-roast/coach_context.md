Quest: ad-t1-asrep-roast (tier 1, active-directory)

Ground truth for the coach:
- dc01 (.51) corp.pentrain.local — no entry creds by design
- svc-legacy / L3gacy2024! — AS-REP roastable (DoesNotRequirePreAuth)
- decoys: mwright, akim (preauth required — GetNPUsers errors on them)
- C:\flags\asrep shared as \\dc01\legacydrop — readable ONLY by svc-legacy;
  flag asrep.txt (injected post-deploy)
- SYSVOL scripts\legacy-sync.txt names svc-legacy (breadcrumb for
  credentialed enum — kerbrute is the unauthenticated route)

Intended path:
kerbrute userenum (unauth) → users.txt → GetNPUsers -no-pass → hashcat
-m 18200 → smbclient -U 'corp\svc-legacy%L3gacy2024!' //dc01/legacydrop
→ asrep.txt → submit

Common wrong turns:
- running GetUserSPNs (needs creds AND svc-legacy has no SPN)
- forgetting -no-pass / -usersfile on GetNPUsers
- hashcat 13100 on the AS-REP blob (that's TGS; AS-REP is 18200)
- trying evil-winrm as svc-legacy (unprivileged — the share is the channel)

Style: tier 1 — the ONLY roast primitive that needs zero creds. Contrast
it with ad-t1-first-domain's kerberoast when coaching.
