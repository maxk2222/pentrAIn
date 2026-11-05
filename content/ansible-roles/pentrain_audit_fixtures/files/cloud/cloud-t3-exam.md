# Platform assurance — evidence bundle

## A — applied RBAC

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: catalogue-ops, namespace: inventory}
rules:
  - apiGroups: ["*", ""]
    resources: ["*"]
    verbs: ["*"]
---
subjects:
  - kind: ServiceAccount
    name: shared-workload   # bound by public-catalogue AND nightly-import
```

## B — flow log extract

```
preview-worker -> 169.254.169.254:80   HTTP 200
preview-worker -> storage.archive-7    HTTPS 200
```

`preview-worker` spec: renders thumbnails for `storefront` uploads.
Egress policy: `0.0.0.0/0`. Mounted credential: `shared-reporting-sa`.

## C — reconciler release record REL-208

```yaml
image: registry.local/atlas/app:latest
signature_check: (field absent)
policy_exception:
  rule: allow-unsigned
  owner: (field absent)
  expires: (field absent)
reconciler_scope: all-namespaces
```
