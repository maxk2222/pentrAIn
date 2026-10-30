# Defense notes — The Pivot

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Credentials in app config | `dbadm` ssh password readable in `/etc/intranet/config.ini` | Move creds to a secrets manager / `0600` file with strict ownership; prefer key-only SSH |
| Flat trust between tiers | Web host can SSH to DB host → lateral movement is trivial | Segment with firewall + dedicated DB users; disable SSH where not needed |
| DB admin via SSH | An attacker pivots and lands as a shell user | Use a jump host / bastion with auditing; no direct SSH into DB tier |
| No egress monitoring | Pivot traffic looks like normal SSH | NetFlow/Zeek on tier boundaries; alert on SSH user != service account |

## Hardening

```bash
# rotate + vault the cred
useradd -r dbapp
sed -i 's/ssh_pass = .*/ssh_pass = <vault-ref>/' /etc/intranet/config.ini
chmod 640 /etc/intranet/config.ini && chown root:www-data /etc/intranet/config.ini

# tighten tier boundary — DB should only accept db traffic, not shells
iptables -A INPUT -p tcp --dport 22 -s <bastion> -j ACCEPT
iptables -A INPUT -p tcp --dport 22 -j DROP

# key-only SSH + forced-command on db tier
sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
```

## Detection

- Zeek/Suricata SSH detection on the tier boundary
- Alert on `ssh` connections to db01 from non-bastion sources
- auditd on db01: executions of `curl`, `wget`, `scp` from unexpected parents

## Further reading

- SSH pivoting: `ssh -J`, `-L`/`-R`, `sshuttle`, `chisel`
- Network segmentation: CIS / NIST 800-53 SC-7
