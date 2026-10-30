Quest: net-t1-open-shares (tier 1, network-recon)

Ground truth for the coach:
- services: SMB (139/445), SNMP (161/udp, community 'public', full tree), SSH
- the leak: /srv/samba/public/backup-runbook.txt → svc-backup / Backup2024!
- flag A: /srv/samba/public/flag.txt — readable anonymously via [public]
- flag B: /srv/samba/finance/flag.txt — [finance] requires valid user svc-backup
- flag C: /home/svc-backup/user.txt — ssh svc-backup@<ip> with the same password
- SNMP second path: sysContact shows svc-backup@corp.local, extend 'backup-memo'
  prints the memo pointing at the runbook — useful if they skip SMB at first

Intended path:
nmap -sV -sU → smbclient -L → public share → runbook → finance share + ssh

Common wrong turns:
- brute-forcing ssh immediately — the creds are handed out on the share
- only scanning TCP — SNMP (UDP 161) is the second discovery path
- forgetting -U / trying the finance share as guest after finding creds

Style: tier 1 — celebrate enumeration wins, keep hints focused on "read what
the share gave you and reuse it".
