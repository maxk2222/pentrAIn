# Reconciliation Authority

> **Track**: Cloud Native · **Tier**: 3 · **Estimated time**: ~30 min

## Scenario

Atlas is enabling automated production reconciliation for a larger set of
services. Review the reconciler's permissions, image policy and exception
process before approving the change.

## Objectives

1. Assess deployment authority and artifact provenance.
2. Submit a hardening report (`reconciler-review`).

## Environment

- **Kali**: `/opt/pentrain-audit/cloud/gitops-hardening-review.md`
- **Report**: `/tmp/pentrain-audit-reports/reconciler-review.md`

## Rules of engagement

- Read-only review of synthetic configuration and evidence.
- Do not apply manifests or modify a repository.
