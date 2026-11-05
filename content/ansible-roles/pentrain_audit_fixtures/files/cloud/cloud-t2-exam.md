# Retail cloud — combined evidence bundle

## IAM policy `catalogue-reader` (as attached)

```json
{
  "Statement": [{
    "Effect": "Allow",
    "Action": ["storage:*", "compute:*"],
    "Resource": "*"
  }]
}
```

- bound workloads: `catalogue-frontend`, `import-job`
- function spec: `catalogue-frontend` serves the namespaced `inventory`
  view; `import-job` reads uploaded CSVs in `inventory/uploads`.

## Egress and metadata

`preview-worker` egress rules: `0.0.0.0/0`, including `169.254.0.0/16`.
The workload mounts the same credential file as `reporting-api`.

## Storage audit extract

```
preview-worker  GET  objects/juniper-archive/report-2026-Q2.csv
preview-worker  GET  objects/juniper-backup/snapshot-manifest.json
```
