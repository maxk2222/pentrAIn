Quest: ad-t1-exam (tier 1 EXAM, active-directory)

Ground truth for the coach:
- pentrain_ad_t1 provides: svc-backup (SPN HTTP/backup..., DA member,
  Backup2024!) + sysvol note
- pentrain_ad_t1_exam adds: svc-report (AS-REP roastable — preauth
  disabled, Report2024!) + C:\flags\exam + runbook breadcrumb
- flags: sysvol scripts\flag.txt, C:\flags\exam\roast.txt,
  C:\flags\domain-admin.txt
- techniques: impacket-GetUserSPNs (kerberoast svc-backup),
  impacket-GetNPUsers -no-pass (asrep svc-report), hashcat 13100/18200

This is an EXAM — coach at the stage level:
- The exam tests whether they know BOTH roast primitives and when each
  applies — GetNPUsers for no-preauth, GetUserSPNs for SPN accounts.
- Redirect to ad-t1-first-domain for the kerberoast mechanics.

Wrong turns: only running GetUserSPNs (misses svc-report), running
GetNPUsers without -usersfile/-no-pass, forgetting the SYSVOL flag is
readable with the cracked account's session or anonymously.
