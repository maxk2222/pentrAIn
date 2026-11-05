# Meridian model registry — deployment configuration

## registry.yaml

```yaml
ingest:
  queue: shared-validation
  loader: generic-object-loader      # torch.load / pickle.load fallback
  checks: [filename-normalize]
validation_worker:
  service_account: registry-worker-sa
  env_mounts: ["/etc/registry", "/srv/projects/*/config"]
publisher_policy:
  signature_required: false
  source_attestation: none
```

## Worker log extract

```
run-184 ingest: filename=final-model.pt -> queued
run-184 load: opened with object-loader (no integrity field present)
run-184 validate: PASSED (schema check only)
```

## Artifact record `run-184`

```json
{"name": "final-model.pt", "uploader": "contrib-77", "size": 1841230,
 "publisher": null, "digest": null, "signature": null}
```

## Model card excerpt

Example config block ships `API_KEY=svc-live-9921` inline.
