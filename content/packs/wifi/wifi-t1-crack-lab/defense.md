# Defense notes — Captured Keys

## What the capture taught

- **Weak PSKs die to wordlists.** `coffee123` survived seconds against a
  20-word list — WPA2's encryption was irrelevant because the *password*
  was the vulnerability. Enterprise-grade passphrases need ≥20 random
  chars, or WPA3-SAE which resists offline dictionary attacks by design.
  Better still: WPA2/3-Enterprise (802.1X) replaces the shared PSK with
  per-user credentials — no shared secret to crack.
- **Captured material is a standing threat.** A handshake file is an
  offline oracle: it can be attacked forever at attacker pace, no lockouts,
  no alerts. Rotating PSKs on suspicion of capture limits exposure; the
  capture here *was* the compromise — the password opened a real account.
- **Password reuse across domains.** The wireless passphrase was also the
  AP admin password — one crack, two systems. Separate credential domains;
  infrastructure accounts should never share passwords with the networks
  they serve.

## Detection opportunities

- Offline cracking is invisible by definition — detection lives *before*
  the capture: unauthorized radios/monitors (WIDS), deauth storms (the
  attacker's loud moment), and rogue capture tools on managed hosts.
- On the account side: logins to `ap-admin` from unexpected sources are
  the last detection mile.

## Takeaway

If a passphrase is in any wordlist, it's already public — the only
question is who's captured the handshake to prove it.
