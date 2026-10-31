# Defense notes — Evidence Pipeline

## What the capture proves

- **Cleartext credentials are forever.** The FTP control channel carried
  `USER`/`PASS` in the clear — and a pcap preserves it verbatim for anyone
  who opens it. Protocols that move credentials must be encrypted (SFTP,
  FTPS) or tunneled; once a cleartext session is captured, rotation is the
  only remediation — and the leaked password was *live on the box*.
- **Evidence shares need access control.** An autoindex HTTP share is fine
  inside a VLAN — but the same pattern on a wider network hands incident
  data (and the creds inside it) to whoever listens next. Put evidence
  behind auth + TLS, with logged access and short retention.
- **Password reuse amplifies captures.** The leaked password wasn't just
  for FTP — it was the account password. Unique credentials per service
  bound the blast radius of any single capture.

## Detection opportunities

- FTP logins outside maintenance windows; FTP from unexpected sources.
- `tshark`/`tcpdump` usage on shared hosts (dual-use tooling).
- SSH logins for service accounts from interactive clients (the account
  that "backs up" shouldn't hop users interactively).

## Takeaway

IR evidence is itself an asset: it contains the keys it documents. Guard
the share as carefully as the systems it describes.
