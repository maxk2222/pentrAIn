Quest: ad-t2-exam (tier 2 EXAM, active-directory)

Ground truth for the coach:
- files01 (/srv/share, guest): flag.txt (flag A), ws-creds.txt →
  CORP\wuser / Work2024!, domain-notes.txt → names svc-metrics + preauth OFF
- ws01: domain member — wuser creds get in (winrm/rdp per the t2 role's
  setup), flag B at C:\flags\workstation.txt
- dc01: svc-metrics AS-REP roastable (Metrics2024!), svc-backup still
  kerberoastable — flag C at C:\flags\exam\roast.txt, flag D
  C:\flags\domain-admin.txt

This is an EXAM — coach at the stage level:
- The chain: share → workstation → domain roast → DC.
- Redirect to ad-t2-corp-lan for the chain mechanics; the exam's twist is
  the second (AS-REP) roast on top of the existing kerberoastable one.

Wrong turns: skipping domain-notes.txt (it names the roastable), trying
to roast before getting on the domain path (GetNPUsers works from kali —
no ws shell needed if you can reach the DC), forgetting flag D needs DA.
