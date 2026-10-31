# Captured Keys

**Situation.** During the last pentest somebody dumped a wireless capture
onto the lab share and never finished the job. The AP it came from is still
in service — and its admin account still uses the wireless passphrase as
its password. Finish the analysis they started.

**Your job**

1. SSH to the lab box as user `wifi` (password `WifiLab-24!`) — your
   tooling and the capture live there.
2. Identify what `/opt/wifi/handshake.cap` contains, then recover the WPA
   passphrase with the provided wordlist.
3. Write the recovered passphrase to `/home/wifi/psk.txt` — that's the
   proof of work.
4. The `ap-admin` account on this host uses that passphrase — ssh in and
   read the flag.

**Note.** This lab simulates WiFi with virtual radios inside the VM —
real 802.11 tooling, no physical antennas required. Tier 2 does it live.

Difficulty: easy · Track: Wireless
