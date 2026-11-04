# The Retrieval Boundary

> **Track**: AI Security · **Tier**: 1 · **Estimated time**: ~20 min

## Scenario

Northstar uses an internal assistant to search business documents and create
support tickets. The security team has asked for a focused review of its
retrieval and tool trust boundaries before a pilot expands to more teams.

## Objectives

1. Identify the tenant-isolation and tool-authorization risks in the supplied evidence.
2. Submit an evidence-backed remediation note (`rag-assessment`).

## Environment

- **Kali**: local review bundle at `/opt/pentrain-audit/ai/rag-boundary.md`
- **Report**: save your assessment to `/tmp/pentrain-audit-reports/rag-boundary.md`

## Rules of engagement

- This is a read-only source and evidence review; do not contact external systems.
- Do not include real credentials or personal data in your report.
- The flag checker validates that your report covers tenant isolation and authorization.
