# Runtime Socket Exception

> **Track**: Cloud Native · **Tier**: 1 · **Estimated time**: ~20 min

## Scenario

The build-monitoring team added a sidecar to report application health. Its
deployment record shows access to a container runtime control socket and a
broad host mount. Review whether those permissions are necessary.

## Objectives

1. Assess the container-to-host trust boundary.
2. Submit a least-privilege report (`runtime-boundary-report`).

## Environment

- **Kali**: `/opt/pentrain-audit/cloud/container-socket-review.md`
- **Report**: `/tmp/pentrain-audit-reports/runtime-boundary.md`

## Rules of engagement

- This is a static deployment review; no container runtime is available.
- Do not connect to a socket or start a container.
