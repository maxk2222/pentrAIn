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

## Radio traps that burned sessions

- `airmon-ng check kill` kills the lab's TRAFFIC generator too — the
  wpa_supplicant client lives inside `pentrain-wifi-ap.service`. Captures
  coming back empty right after a check-kill means you shot your own
  client: `sudo systemctl restart pentrain-wifi-ap` (scoped-allowed),
  wait ~20s for re-assoc, then capture again. Verify with
  `pgrep -a wpa_supplicant` before blaming the radio.
- WiFi-lab quests run ALL radio commands on the lab box via
  `ssh wifi@<lab>` + `sudo -S` — NEVER on Kali. If `iw dev` on Kali shows
  wlan* interfaces, you loaded `mac80211_hwsim` on the wrong host; unload
  it (`sudo modprobe -r mac80211_hwsim`) — a Kali-side monitor captures
  nothing because no lab AP is in range.
- `modprobe -r mac80211_hwsim` + bare `modprobe mac80211_hwsim` rebuilds
  with the default radios=2 and DELETES the attack interface (phy#1/wlan1)
  for good. Always reload with `radios=3`, and only after killing the
  daemons that hold the phys: `sudo pkill hostapd; sudo pkill
  wpa_supplicant` (the oneshot unit's `systemctl stop` cannot reap `-B`
  daemonized children). Then `systemctl restart pentrain-wifi-ap` and
  `iw dev` must show wlan0+wlan1+wlan2 before capturing again.
- Scoped-sudo on the lab allows single binaries only — `sudo bash -c …`
  and `sudo bash /tmp/x.sh` are denied even when every inner command is
  allowed. Chain per-command: `sudo -S pkill x; sudo -S modprobe …`.
- Non-login ssh PATH lacks /usr/sbin: bare `iw`/`airodump-ng` return
  `command not found` — always prefix with `sudo -S` (sudo's secure_path
  covers it) or call the full path.
