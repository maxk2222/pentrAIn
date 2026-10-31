Quest: ad-t1-exam (tier 1 EXAM, active-directory)

Ground truth for the coach:
- pentrain_ad_t1 provides: intern/Welcome2024! (domain users), svc-backup
  (SPN HTTP/backup..., DA member, Backup2024!) + sysvol note
- pentrain_ad_t1_exam adds: svc-report (AS-REP roastable — preauth
  disabled, Report2024!), C:\flags\exam shared as \\dc01\reportdrop
  (readable ONLY by svc-report) + runbook breadcrumb in SYSVOL scripts
- flags: sysvol scripts\flag.txt (any domain user — intern works),
  C:\flags\exam\roast.txt via the reportdrop share (svc-report session),
  C:\flags\domain-admin.txt (svc-backup — DA, e.g. evil-winrm/psexec)
- techniques: impacket-GetUserSPNs (kerberoast svc-backup),
  impacket-GetNPUsers -no-pass (asrep svc-report), hashcat 13100/18200,
  smbclient //dc01/reportdrop with the cracked svc-report creds

This is an EXAM — coach at the stage level:
- The exam tests whether they know BOTH roast primitives and when each
  applies — GetNPUsers for no-preauth, GetUserSPNs for SPN accounts.
- Redirect to ad-t1-first-domain for the kerberoast mechanics and
  ad-t1-asrep-roast for the no-preauth primitive.

Wrong turns: only running GetUserSPNs (misses svc-report), running
GetNPUsers without -usersfile/-no-pass, trying to winrm as svc-report
(no admin rights — the drop share is the loot channel), forgetting the
SYSVOL flag is readable with any domain session.
