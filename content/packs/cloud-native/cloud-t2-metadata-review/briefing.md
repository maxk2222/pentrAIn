# Metadata Boundary

> **Track**: Cloud Native · **Tier**: 2 · **Estimated time**: ~25 min

## Scenario

Juniper's document preview worker generated an unexpected access record.
Review the synthetic architecture and determine whether its network and cloud
identity permissions match its limited task.

## Objectives

1. Assess metadata-network reachability, egress and identity scope.
2. Submit a remediation report (`metadata-review`).

## Environment

- **Kali**: `/opt/pentrain-audit/cloud/metadata-review.md`
- **Report**: `/tmp/pentrain-audit-reports/metadata-boundary.md`

## Rules of engagement

- This is a local evidence review; no cloud account or endpoint is configured.
- Do not request or reproduce credentials.
