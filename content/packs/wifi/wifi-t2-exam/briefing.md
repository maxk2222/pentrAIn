# Exam: Ops Channel

**Tier-2 capstone.** Live wireless attack — the full cycle, on a network
you haven't touched before.

**Situation.** `ops-wifi` (channel 1) is the operations network; its
config backup sits encrypted at `/opt/wifi/backup.enc` — and nobody
remembers the passphrase. There's a client associated right now.
You know what to do.

**The lab.** `wifilab01` (10.x.10.25), `wifi` / `WifiLab-24!`.
`wlan0` = AP, `wlan2` = client, `wlan1` = yours.

**Your job**

1. Survey, lock channel 1, watch the client.
2. Deauth → capture the handshake → crack the PSK.
3. The PSK is also the backup's openssl key: decrypt
   `/opt/wifi/backup.enc` to `/home/wifi/backup.txt`.
4. And it's the `wifi-admin` password — ssh in, read the flag.

**Requirements:** ALL Tier-2 wireless quests must be solved first.

Difficulty: medium (exam) · Track: Wireless
