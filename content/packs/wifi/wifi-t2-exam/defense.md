# Defense notes — Exam: Ops Channel

## What the exercise taught

- **One secret, three doors.** The wireless passphrase encrypted the
  config backup AND passworded the admin account — a single offline crack
  unrolled into network access, config disclosure, and host compromise.
  Credential domains must be *separate*: network PSK ≠ data key ≠ account
  password.
- **Encrypted-at-rest ≠ safe when keys travel together.** `backup.enc`
  was AES-256 — perfectly strong — but the key was a human WiFi password
  recoverable from a handshake. Key management IS the security of
  encrypted backups: dedicated keys, KMS/HSM, or asymmetric wrapping.
- **Re-associating clients are permanent oracles.** The ops client rejoined
  every 15 seconds, handing out fresh handshake material constantly. Any
  device that roams or retries aggressively keeps the attack surface open.

## Detection opportunities

- Deauth bursts on ops channels (loud moment).
- Repeated client re-association beyond normal roaming.
- openssl/gpg invocations on config-backup paths by unexpected users.

## Takeaway

AES-256 protects the backup; a guessable PSK protects the key — the
weakest ring in the chain decides which one the attacker pulls.
