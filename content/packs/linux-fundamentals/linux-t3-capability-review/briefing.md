# Permission Baseline

> **Track**: Linux Fundamentals · **Tier**: 3 · **Estimated time**: ~20 min

## Scenario

The batch-processing service has completed a permissions review. The collected
inventory contains privileges that may exceed its documented duties. Compare
the evidence with the approved baseline and recommend a least-privilege change.

## Objectives

1. Identify privileges outside the service's stated need.
2. Submit an evidence-backed recommendation (`capability-review`).

## Environment

- **Kali**: inventory at `/opt/pentrain-audit/linux/capability-review.md`
- **Report**: `/tmp/pentrain-audit-reports/capability-review.md`

## Rules of engagement

- This is a read-only inventory exercise.
- Do not apply permissions or attempt to access unrelated system files.
