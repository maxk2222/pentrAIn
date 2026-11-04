# Release Gate

> **Track**: Cloud Native · **Tier**: 1 · **Estimated time**: ~20 min

## Scenario

Atlas deploys containerized services through a GitOps workflow. The platform
team wants an independent review of contribution trust, runner isolation and
artifact identity before connecting the workflow to production.

## Objectives

1. Trace the release authority and identify trust-boundary failures.
2. Submit a prioritized remediation note (`gitops-review`).

## Environment

- **Kali**: workflow bundle at `/opt/pentrain-audit/cloud/gitops-review.md`
- **Report**: `/tmp/pentrain-audit-reports/gitops-review.md`

## Rules of engagement

- Review only the supplied synthetic configuration.
- Do not run pipeline commands or attempt to access an external repository.
