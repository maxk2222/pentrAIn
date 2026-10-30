# Defense notes — Wiretap

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| FTP in cleartext | Credentials + file contents on the wire | SFTP/FTPS; disable plaintext FTP entirely |
| Password reuse (FTP account = SSH account) | One sniffed login → remote shell | Unique credentials per service; key-only SSH |
| Payload staged under `/usr/local/lib` | Persistence survives a casual look | FIM on system dirs (AIDE), alert on new files outside package manager |
| Exfil over the same FTP session | Data left the network unchallenged | Egress filtering + DLP on plain protocols |

## Audit commands

```bash
# hunt staged payloads in the places this case used
ls -la /usr/local/lib/ /var/lib/ | grep -vE '^(total|d|l)'
find /usr/local /var/lib -type f -newer /var/log/dpkg.log 2>/dev/null

# replay the evidence the way the trainee sees it
tshark -r /evidence/capture.pcap -Y ftp -T fields -e ftp.request.command -e ftp.request.arg
tshark -r /evidence/capture.pcap -qz follow,tcp,ascii,0
```

## Detection

- NIDS signatures for `USER`/`PASS` on port 21 in plaintext
- alert on FTP sessions crossing the perimeter (both directions)
- e2e: correlate new files in system dirs with recent inbound sessions

## Further reading

- RFC 959 (FTP) — why the data channel is a *separate* stream
- AIDE/Tripwire file-integrity monitoring basics
