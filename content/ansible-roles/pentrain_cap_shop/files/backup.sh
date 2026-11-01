#!/bin/sh
# nordmarkt shop — archive the site tree + db init for the office NAS.
# Runs from cron as root; the deploy group maintains the script
# (kirsten tweaks it during campaign weeks).
ts=$(date +%Y%m%d-%H%M%S)
mkdir -p /var/backups/shop
tar czf "/var/backups/shop/site-$ts.tgz" -C /opt/shop site db 2>/dev/null
# keep the last 20 archives
ls -1t /var/backups/shop/site-*.tgz 2>/dev/null | tail -n +21 | xargs -r rm -f
