# Exam: Dual Band

**Tier-3 capstone.** Every wireless technique from the track, back to back,
under time pressure.

**Situation.** Final assessment: two WPA2 networks on air —
`mgmt-wifi` (ch6) and `exec-wifi` (ch11). Both need to fall. Intel says
one leaks a PMKID to anyone who asks; the other has an executive's client
associated and listening.

**The lab.** `wifilab01` (10.x.10.25), `wifi` / `WifiLab-24!`, four
radios — `wlan1` is your attack interface.

**Your job**

1. Map both networks — which attack applies to which?
2. Harvest mgmt-wifi's PMKID clientless; deauth exec-wifi's client for the
   handshake. `wlan1` is one interface — work the two attacks sequentially.
3. Crack both.
4. Report: `/home/wifi/exam-report.txt` must name both networks with
   both recovered keys.
5. `mgmt-admin` takes the mgmt passphrase — ssh in, take the flag.

**Requirements:** ALL Tier-3 wireless quests must be solved first.

Difficulty: hard (exam) · Track: Wireless
