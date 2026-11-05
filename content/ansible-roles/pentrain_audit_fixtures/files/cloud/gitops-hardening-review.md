# Atlas production reconciler — applied configuration

## reconciler-config.yaml

```yaml
apiVersion: atlas/v1
kind: Reconciler
metadata: {name: prod-reconciler}
spec:
  serviceAccount: cluster-admin-binding
  watchNamespaces: ["*"]
  source:
    repo: git.corp/atlas/prod-manifests
    branchProtection: optional
  imagePolicy:
    allowedTags: ["*"]
    requireSignature: false
```

## Release record REL-208 (registry extract)

```json
{
  "image": "registry.local/atlas/app",
  "tag": "latest",
  "deployed_at": "2026-10-14T09:12Z",
  "source_revision": null,
  "signature_verified": null,
  "approved_by": null
}
```

## Policy exceptions

```yaml
- rule: allow-unsigned-images
  granted_to: prod-reconciler
  owner: null
  expires: null
```
