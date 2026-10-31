# No Client Needed

**Situation.** A security review turned up a complaint: an open network
called `free-wifi` appeared near the office and somebody's laptop joined
it. While you're checking the airspace, enumerate everything — including
the corporate `secure-net`, which was recently "hardened."

**The lab.** `wifilab01` (10.x.10.25), user `wifi` / `WifiLab-24!`.
Three attacker-relevant radios: `wlan0` hosts secure-net (WPA2, ch6),
`wlan2` hosts the open `free-wifi` (ch11), `wlan1` is yours.

**Your job**

1. Survey the airspace — name every BSSID/SSID and its security.
2. Document the rogue: write its SSID to `/home/wifi/rogue.txt`.
3. `secure-net` leaks a PMKID — grab it clientless with hcxdumptool,
   convert to hashcat format, save as `/home/wifi/pmkid.22000`.
4. Crack the hash, then ssh the `secadmin` account (its password is the
   PSK) and read the flag.

Difficulty: hard · Track: Wireless
