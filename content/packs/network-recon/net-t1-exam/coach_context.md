Quest: net-t1-exam (tier 1 EXAM, network-recon)

Ground truth for the coach:
- ftp 21: anonymous read → /srv/ftp/pub/flag.txt (flag A) + decoy docs
- smb 445: guest share `it` → field-access.txt → fieldtech / Field2024!
- ssh: fieldtech login → /home/fieldtech/user.txt (flag B)
- privesc: sudo -l → NOPASSWD /usr/bin/find →
  `sudo find . -exec /bin/sh \; -quit` → /root/root.txt (flag C)

This is an EXAM — coach at the stage level, not the command level:
- Confirm coverage: did they enumerate ALL services or stop at the first open
  one? The exam tests breadth + chain discipline.
- Redirect "just tell me" requests to net-t1-services / net-t1-open-shares —
  same techniques, different box.

Wrong turns: trying ssh brute force (creds are on the wire, not guessed),
using ftp write (read-only), forgetting `sudo -l` after getting the shell.
