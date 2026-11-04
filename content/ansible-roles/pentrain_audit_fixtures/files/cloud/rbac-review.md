# Retail cluster — manifest review

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

The workload only needs to read ConfigMaps and list Deployments in the
`inventory` namespace. The same service account is mounted in the public
catalogue pod and the scheduled import job.

Review questions: identify excess verbs/resources, excess API groups and
whether the identity should be shared across both workloads.
