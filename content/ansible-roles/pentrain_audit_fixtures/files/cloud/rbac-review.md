# Retail cluster — applied manifests (kubectl get -o yaml)

## role-inventory-reader.yaml

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: inventory-reader
  namespace: inventory
rules:
  - apiGroups: ["", "apps"]
    resources: ["*"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

## rolebinding-catalogue-sa.yaml

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: inventory-reader-binding
  namespace: inventory
subjects:
  - kind: ServiceAccount
    name: shared-workload
    namespace: default
roleRef:
  kind: Role
  name: inventory-reader
```

## Workloads bound to `shared-workload`

- Deployment `public-catalogue` (namespace `storefront`)
- CronJob `nightly-import` (namespace `inventory`)

## Application spec (team wiki)

`public-catalogue` reads ConfigMaps and lists Deployments in `inventory`.
`nightly-import` reads ConfigMaps in `inventory`. Neither workload creates,
updates or deletes cluster objects.
