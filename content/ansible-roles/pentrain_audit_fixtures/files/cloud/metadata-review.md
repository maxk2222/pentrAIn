# Juniper — workload deployment bundle

## workload-deploy.yaml (as applied)

```yaml
workload: preview-worker
service_account: shared-reporting-sa
egress_rules:
  - 0.0.0.0/0:443
  - 0.0.0.0/0:80
  - 169.254.0.0/16:*
network_policy: default-allow
```

## IAM binding `shared-reporting-sa`

- bound workloads: `preview-worker`, `reporting-api`
- granted scopes: `storage.read` on projects `juniper-a`, `juniper-b`,
  `juniper-archive`, `juniper-backup`
- credential type: long-lived service account key

## Function spec (team wiki)

`preview-worker` renders document thumbnails for uploaded files in the
`juniper-a` storage project. It calls the object API for `juniper-a` only.

## Flow log extract (CLOUD-41)

```
10.1.10.44 -> 169.254.169.254:80  HTTP  200  1321 bytes
10.1.10.44 -> storage.juniper-b   HTTPS 200  8440 bytes
```
