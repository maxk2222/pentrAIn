# Northstar developer assistant — MCP configuration review

## Service inventory

- Tool server is shared by development and production assistants.
- Tool discovery returns descriptions supplied by each registered integration.
- The registration service does not record an approving owner for tool changes.
- A repository-reading tool can access paths outside its declared workspace.

## Intended policy

- Each tool has a named owner and a reviewed, versioned schema.
- Read-only tools receive only their designated data source.
- Tool outputs and descriptions are untrusted data, not policy.
- Changes are approved, logged and attributable to a publisher.

## Review evidence

Change record `MCP-22` shows a tool description changed between two releases
without a corresponding approval event. No production action is demonstrated.
