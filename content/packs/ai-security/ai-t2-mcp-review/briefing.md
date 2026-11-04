# Protocol Ownership

> **Track**: AI Security · **Tier**: 2 · **Estimated time**: ~25 min

## Scenario

Northstar is standardizing tool integrations for internal assistants. A
reviewer found changes to a production tool without a clear owner approval.
Assess the supplied service inventory and recommend controls.

## Objectives

1. Review tool ownership, permissions and output trust.
2. Submit an evidence-backed assessment (`mcp-governance-report`).

## Environment

- **Kali**: `/opt/pentrain-audit/ai/mcp-review.md`
- **Report**: `/tmp/pentrain-audit-reports/mcp-governance.md`

## Rules of engagement

- This is a static review; no MCP server is running.
- Do not submit tool calls or attempt to access repository data.
