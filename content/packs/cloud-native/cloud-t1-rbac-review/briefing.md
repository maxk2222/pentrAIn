# The Overbroad Role

> **Track**: Cloud Native · **Tier**: 1 · **Estimated time**: ~20 min

## Scenario

The retail platform team is preparing a catalogue service for production.
An internal review has flagged a shared Kubernetes service identity with
permissions broader than its documented job requirements.

## Objectives

1. Compare the role permissions to the workload's stated needs.
2. Submit a least-privilege recommendation (`rbac-review`).

## Environment

- **Kali**: review bundle at `/opt/pentrain-audit/cloud/rbac-review.md`
- **Report**: `/tmp/pentrain-audit-reports/rbac-review.md`

## Rules of engagement

- This is a read-only manifest review; do not connect to a Kubernetes cluster.
- Recommend controls and verification using synthetic test identities only.
