Quest: linux-t3-exam (tier 3 EXAM, linux-fundamentals)

Ground truth for the coach:
- bastion01 (.50, open): pre-auth ssh Banner → deployer / Deploy2024!
  home has DEPLOY.txt → app@app01 / AppTier2024!
- app01 (.51): nftables accepts only bastion + router.
  ssh -J deployer@bastion app@app01. sudo -l → journalctl → `!/bin/sh`.
  /opt/app/config.yml → dba / DbAdmin2024!
- db01 (.52): nftables accepts only app01 + router.
  ssh -J deployer@bastion,app@app01 dba@db01 — dba is full sudoer.
- flags: deployer/user.txt, /root/app.txt (journalctl root), /root/db.txt

This is an EXAM — coach at the stage level:
- The chain discipline is the exam: loot → creds → hop → repeat.
- Redirect to linux-t3-pivot (ProxyJump mechanics) and
  linux-t2-privesc-chain (sudo enumeration) if stuck.
- If they try reaching app01/db01 directly from kali: firewalled — the
  point is the jump chain.

Wrong turns: brute-forcing app01 (it drops their packets), forgetting
-J takes a comma list for multi-hop, journalctl without pager escape
(export PAGER=cat breaks it — needs a real pager or smaller term).
