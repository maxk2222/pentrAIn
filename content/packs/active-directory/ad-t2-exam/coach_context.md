Quest: ad-t2-exam (tier 2 EXAM, active-directory)

Ground truth for the coach:
- files01 (/srv/share, guest): flag.txt (flag A), ws-creds.txt →
  CORP\wuser / Work2024!, domain-notes.txt → names svc-metrics + preauth OFF
- ws01: domain member — wuser is local admin there (winrm/rdp),
  flag B at C:\flags\workstation.txt; C:\ops\dc-note.txt →
  CORP\adm-ops / D@main2024! (Domain Admin)
- dc01: svc-metrics AS-REP roastable (Metrics2024!) — plain domain user,
  its loot channel is \\dc01\metricsdrop (read only by svc-metrics) →
  flag C roast.txt. Flag D C:\flags\domain-admin.txt via adm-ops
  (evil-winrm/psexec — DA rights required).

This is an EXAM — coach at the stage level:
- The chain: share → workstation → DA note → DC; plus the AS-REP side-quest.
- Redirect to ad-t2-corp-lan for the chain mechanics; the exam's twist is
  the extra roastable named in the maintenance notes.

Wrong turns: skipping domain-notes.txt (it names the roastable), trying to
winrm as svc-metrics (no admin rights — the metricsdrop share is the channel),
forgetting flag D needs DA creds (they're on ws01, not the share).
