# The Pivot

The range now looks like a real intranet: an `web01` frontend and a `db01`
database box. `db01`'s firewall only accepts SSH from `web01` — direct access
from your Kali is dropped.

## Objectives

1. Get onto `web01` — find what's exposed.
2. Discover credentials or keys that the app tier uses to reach the DB tier.
3. Pivot into `db01` — via `ssh -J`, port-forwarding, sshuttle, or a manual hop.
4. Submit both flags: `/var/www/flag.txt` and `/root/db.txt`.

## Notes

- Flag on web01 is web-readable-adjacent — think about *where* the app serves files.
- Once you have dbadm's password, the pivot is a one-liner. The root flag needs
  a bit more privilege on db01 — look around when you land.
