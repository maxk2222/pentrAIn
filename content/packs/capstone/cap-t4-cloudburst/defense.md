# Defense notes — Cloudburst

## Vulnerability 1 — SSRF on the edge (urllib honours file:// and internal names)

- **Weakness**: `/preview?url=` fetches arbitrary URLs server-side — local
  files via `file://`, and internal names like `http://k8s01/…` that must
  never be reachable through the public surface.
- **Detect**: preview requests to `file://`, loopback, RFC1918 or internal
  names; egress logs showing edge01→k8s01 traffic with no business reason.
- **Fix**: strict scheme allowlist (`https:` only), resolve + validate IPs
  against private ranges (and after redirects); route previews through an
  egress sandbox with no internal reachability.
- **Verify**: `?url=file:///etc/passwd` and `?url=http://k8s01/` both fail.

## Vulnerability 2 — debug exec endpoint in a production pod

- **Weakness**: `/exec?cmd=` is command injection as a shipped feature.
- **Detect**: HTTP logs with `/exec?cmd=`; unexpected sh children in the
  pod; admission policies flagging debug routes.
- **Fix**: remove debug code from prod images; enforce endpoint policies;
  scan images for RCE-surface before rollout.
- **Verify**: `/exec` returns 404; no pod ships `/bin/sh`-backed handlers.

## Vulnerability 3 — over-privileged SA + privileged pods

- **Weakness**: shop-sa reads prod secrets, creates pods, reads pod logs —
  one token = cluster escape via `privileged` + `hostPath`.
- **Detect**: `can-i --list` on the SA shows prod verbs; pod-create events
  with `securityContext.privileged` or hostPath volumes.
- **Fix**: least-privilege RBAC per namespace, `automountServiceAccountToken:
  false` where unused; enforce `restricted` Pod Security Standards and an
  admission webhook rejecting privileged/hostPath pods.
- **Verify**: the escape pod spec is rejected at admission; the SA can't
  list prod secrets.

## Vulnerability 4 — node filesystem exposed via kind extraMounts

- **Weakness**: `/` of the VM mounted into the kind node at `/host` — a
  privileged pod's hostPath mount of `/host` reads the node's own root.
- **Detect**: cluster configs with hostPath extraMounts covering `/`.
- **Fix**: never mount node root into the cluster; scope mounts to exactly
  the directory pods need (like /mnt/labflags) and mount readOnly.
- **Verify**: `cat /host/root/k8s-flag.txt` inside a pod fails because the
  mount point does not exist.
