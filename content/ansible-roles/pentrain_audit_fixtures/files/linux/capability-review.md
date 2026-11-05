# ops-tools audit — capability & service evidence

## getcap -r output

```
/usr/bin/backup-tool = cap_dac_override+ep
/usr/bin/backupd     = cap_dac_override+ep
/usr/bin/diag        = cap_sys_admin+ep
/usr/sbin/log-viewer = cap_dac_read_search+ep
```

## Service unit `backupd.service`

```ini
[Service]
User=backupd
Group=backupd
AmbientCapabilities=CAP_DAC_OVERRIDE CAP_SYS_ADMIN
NoNewPrivileges=false
ProtectSystem=off
```

## Cron entry

```
*/5 * * * * backupd /usr/bin/backupd --full
```

## Ops note (team wiki)

The backup daemon reads files under `/etc`, `/var/lib`, and `/home` for
the nightly archive. Diagnostics run on demand.
