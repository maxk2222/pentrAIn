# Defense notes — The Whole Incident

## What went wrong

| Issue | Evidence | Fix |
|---|---|---|
| Executable uploads | shell.phtml + POST in pcap/log | Allowlist + no-exec upload dir |
| DB creds in /opt/shop/db.ini | web shell reads them → lateral move | Secrets vault; service accounts with network ACLs |
| Password ssh between tiers | dbmaint password = free lateral | Key-only + per-tier accounts; no interactive db-admin ssh |
| Loot staging in /var/backups | loot.tar.gz + sudo tar line | FIM on backup dirs; alert on tar/gzip by service users |
| Weak IR creds (analyst/analysis) | Documented for the range | Real IR: vaulted keys, MFA, break-glass |

## The timeline this exam teaches

```text
09:12:31  POST /upload.php          (pcap + access.log agree)
09:12:47  GET shell.phtml?c=id      (webshell confirmed)
09:13:20  c=grep db → /opt/shop/db.ini read
09:14:05  sshpass ssh dbmaint@db02  (last web log line)
09:14:12  auth.log db02: dbmaint accepted from web02
09:14:19  sudo tar czf loot.tar.gz  (staging)
09:15:44  session closed            (exfil complete)
```

## Detection

- Web: POST→GET webshell pattern in access.log within seconds
- Host: www-data spawning ssh/sshpass — never legitimate
- Network: east-west ssh between tiers from a web host
