---
id: wifi-radio
title: WiFi radio traps — airmon check-kill, mac80211_hwsim rebuild, scoped sudo
triggers: [airmon, mac80211, hostapd, wpa_supplicant, wlan, pentrain-wifi-ap, radios=3]
---

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
