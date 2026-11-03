# Defense notes — Soft-Schedule

## Vulnerability 1 — debug endpoint in production

- **Weakness**: `/exec?cmd=` executes arbitrary shell inside the pod — a
  debug route shipped to prod with no auth.
- **Detect**: HTTP access logs with `/exec?cmd=`; process trees inside the
  pod spawning sh children; Falco/eBPF alerts on unexpected exec.
- **Fix**: never ship debug routes — gate behind build flags; strip them in
  prod images; enforce authz middleware + admission policies (OPA/Kyverno)
  that reject images containing such endpoints.
- **Verify**: `curl http://app01/exec?cmd=id` must return 404, always.

## Vulnerability 2 — over-privileged service account (RBAC)

- **Weakness**: `shop-sa` (shop namespace) can read secrets AND create pods
  in `prod` — one stolen token equals cluster-adjacent root.
- **Detect**: `kubectl auth can-i --list --as system:serviceaccount:shop:shop-sa`
  shows prod verbs; audit logs for secret-list + pod-create by a workload SA.
- **Fix**: least privilege — a pod SA needs nothing beyond its own
  namespace; split duties per deployment; prefer short-lived bound tokens;
  `automountServiceAccountToken: false` where unused.
- **Verify**: `can-i create pods -n prod` as the SA must answer `no`.

## Vulnerability 3 — privileged pod + hostPath == node compromise

- **Weakness**: anyone who can create pods can ask for `privileged:true` +
  hostPath `/` — the node is the sandbox boundary and it evaporates.
- **Detect**: pod-create requests with `securityContext.privileged` or
  hostPath volumes; PSA admissions logging `baseline`/`restricted` rejects.
- **Fix**: enforce `restricted` Pod Security Standards cluster-wide;
  admission-webhook reject privileged + hostPath; run nodes where even
  privileged containers stay unprivileged (userns, gVisor/Kata).
- **Verify**: the escape pod spec must be REJECTED at admission.
