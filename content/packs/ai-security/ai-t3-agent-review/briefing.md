# Agent Permission Boundaries

> **Track**: AI Security · **Tier**: 3 · **Estimated time**: ~30 min

## Scenario

FinSight is splitting an analytics agent into planner, query and reporting
services. Review the supplied architecture evidence and determine whether its
identity and data boundaries match the analyst's approved scope.

## Objectives

1. Assess policy enforcement, identity scope and auditability.
2. Submit a prioritized report (`agent-boundary-report`).

## Environment

- **Kali**: `/opt/pentrain-audit/ai/agent-boundary-review.md`
- **Report**: `/tmp/pentrain-audit-reports/agent-boundaries.md`

## Rules of engagement

- Static architecture review only; no agent or database is running.
- Do not submit queries or attempt to access records.
