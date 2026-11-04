# Batch processor — permission inventory

## Approved baseline

The service account `batchsvc` may read files below `/srv/batch/input` and
write results below `/srv/batch/output`. It does not need to change user IDs,
inspect unrelated files or administer the host.

## Collected inventory

```text
/usr/local/bin/batch-import cap_dac_read_search=ep
/usr/local/bin/batch-runner cap_setuid,cap_sys_admin=ep
```

The inventory was collected from an authorized lab image. Recommend the
smallest permission set, an ownership change where appropriate and a
verification procedure that confirms unrelated system files remain
inaccessible.
