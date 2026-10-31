# Live Air

**Situation.** A WPA2 network called `corp-wifi` is on the air, and a
corporate client is glued to it. Nobody hands you a capture this time —
you have to make one.

**The lab.** `wifilab01` (10.x.10.25) runs three virtual radios:

- `wlan0` — hosts the AP `corp-wifi` (channel 6)
- `wlan2` — a client that stays associated and rejoins when kicked
- `wlan1` — **your** radio: monitor mode, capture, deauth

SSH in as `wifi` / `WifiLab-24!`.

**Your job**

1. Put `wlan1` in monitor mode.
2. Capture `corp-wifi` traffic on channel 6 — watch the client station.
3. Deauth the client, catch the re-association handshake.
4. Crack the PSK (the lab wordlist covers the corp password policy),
   write it to `/home/wifi/psk.txt`.
5. `wifi-admin`'s account uses the PSK — ssh in and take the flag.

Difficulty: medium · Track: Wireless
