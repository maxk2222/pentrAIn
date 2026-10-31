# Exam: Backup Channel

**Tier-1 capstone.** Combines the wireless skills of this tier — no new
techniques, but nothing is handed to you twice.

**Situation.** The ops team rotated the backup WiFi passphrase this
quarter — and promptly lost it. A fresh capture and the site survey are
in `/opt/wifi`. Recover the passphrase, document the finding properly,
and use it.

**Your job**

1. SSH to `wifilab01` as `wifi` / `WifiLab-24!`.
2. Review the site survey — which network does `exam-handshake.cap`
   actually belong to?
3. Crack the capture. The wordlist knows the rotation season.
4. Write `analysis.txt` in `/home/wifi` naming the network **and** the
   recovered key — a pentest finding that can't be read isn't a finding.
5. The `backup-admin` account uses the PSK — ssh in, read the flag.

**Requirements:** ALL Tier-1 wireless quests must be solved first.

Difficulty: easy (exam) · Track: Wireless
