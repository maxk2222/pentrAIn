# Defense notes — Exam: Backup Channel

## What the exercise taught

- **Seasonal PSKs are predictable PSKs.** `winter2024` is a rotation
  *pattern*, not a rotation — the wordlist covered it by calendar.
  Rotation only helps if each value is independently random; predictable
  schemes let attackers skip rotation entirely by guessing the pattern.
- **Backups channels are full-privilege paths.** The "backup" network had
  an admin account with real flags — secondary/infrastructure SSIDs get
  less hardening attention and are prime targets. Inventory every SSID,
  harden like production.
- **Survey baseline vs. reality.** The site survey *listed* the authorized
  networks — comparing it against what's actually on air is the cheapest
  rogue-detection control that exists, and it's exactly what the exam
  made you do.

## Detection opportunities

- Mismatch reports: capture-vs-survey diffing, unexpected SSIDs, unknown
  BSSIDs in beacons.
- Account hygiene: `backup-admin` sharing the wireless PSK collapsed two
  security domains into one crack.

## Takeaway

A passphrase that follows a pattern rotates the way a revolving door
locks — mechanically, impressively, and without stopping anyone who
bothers to watch it once.
