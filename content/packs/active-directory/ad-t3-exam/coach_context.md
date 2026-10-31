Quest: ad-t3-exam (tier 3 EXAM, active-directory)

Ground truth for the coach:
- pentrain_ad_t3_* provides the full kill-chain environment (see the
  teaching quest's roles — ws sessions, delegation, roastables)
- exam role adds: jholt / Summer2024! (weak domain user — sprayable),
  onboarding.txt in SYSVOL naming him, C:\flags\exam shared as
  \\dc01\helpdeskdrop (read only by jholt)
- flags: C:\flags\exam\spray.txt (via helpdeskdrop as jholt),
  C:\flags\workstation.txt (ws01), C:\flags\dc2.txt (dc02),
  C:\flags\krbtgt.txt (dc01)
- chain: spray jholt → smbclient helpdeskdrop (spray flag) + \\ws01\ops
  anonymous share → wadmin → ws01/ws02 → dc-script.ps1 → svc-rep DA →
  secretsdump -just-dc → dc02

This is an EXAM — coach at the stage level:
- This is the capstone: spray → enum → roast → lateral → sync.
- Redirect to ad-t3-kill-chain for the full-chain mechanics; the exam
  adds the spray entry point on top.

Wrong turns: password spraying without a user list (GetADUsers/
kerbrute first), burning lockouts with fast sprays (one pass per user
per window), stopping at DA when the DCSync flag is the goal.
