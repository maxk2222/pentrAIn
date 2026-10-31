# Cheatsheet — offline WPA cracking

## Inspect a capture

```bash
aircrack-ng handshake.cap        # BSSID, ESSID, encryption, handshake count
capinfos handshake.cap           # capture details (tshark suite)
```

## Crack with aircrack

```bash
aircrack-ng -w wordlist.txt handshake.cap
# → KEY FOUND! [ passphrase ]
```

## hashcat path (22000 format)

```bash
hcxpcapngtool -o hash.22000 handshake.cap
hashcat -m 22000 hash.22000 wordlist.txt
hashcat -m 22000 hash.22000 --show
```

## WPA key-space basics

- PSK = PBKDF2(passphrase, ssid, 4096) — the SSID is salt, so rainbow
  tables are per-network.
- Dictionary attacks only catch human passwords — long random PSKs are
  out of reach.
- The 4-way handshake IS the oracle: no AP contact needed once captured.
