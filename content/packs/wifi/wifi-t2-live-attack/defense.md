# Defense notes — Live Air

## What the deauth taught

- **Deauthentication is unauthenticated by design.** 802.11 management
  frames lack protection in WPA2 — anyone can spoof a deauth and force
  re-association, producing exactly the handshake an attacker needs.
  WPA3's mandatory Protected Management Frames (802.11w) fix this — the
  single biggest upgrade for the classic attack chain.
- **The client is the weak link.** Every reconnect is a fresh oracle
  capture opportunity. Devices that roam or have unstable signal rejoin
  constantly — attackers don't even need to force it, just wait.
- **Human PSKs still end the game.** `sunshine2024` fell to a 15-word
  list. Random ≥16-char passphrases push dictionary cost past practical
  limits even with captured material.

## Detection opportunities

- **Deauth floods are loud.** A burst of deauth frames = signature event
  for any WIDS/WIPS — and the only stage of this attack visible on air.
- **Monitor-mode anomaly**: unexpected radios on-site, unexpected BSSIDs
  after a deauth push (evil-twin follow-ons).
- Infrastructure side: repeated auth events on the target account, logins
  from the attacker's address — the PSK-as-password reuse made the wireless
  compromise into a host compromise.

## Takeaway

One deauth frame, one weak passphrase — WPA2's handshake is a vault door
whose combination is often on a sticky note. PMF + strong PSKs + WPA3 is
the stack; WIDS is the alarm.
