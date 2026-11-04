# Model Provenance

> **Track**: AI Security · **Tier**: 2 · **Estimated time**: ~25 min

## Scenario

Meridian's internal model registry sends uploaded artifacts to a validation
worker. The security team wants a release-readiness review of artifact
provenance, worker permissions and secret handling.

## Objectives

1. Assess the artifact and worker trust boundaries.
2. Submit a remediation report (`model-provenance-report`).

## Environment

- **Kali**: `/opt/pentrain-audit/ai/model-registry-review.md`
- **Report**: `/tmp/pentrain-audit-reports/model-provenance.md`

## Rules of engagement

- Static review only; no model file is supplied or loaded.
- Do not create or execute a serialized artifact.
