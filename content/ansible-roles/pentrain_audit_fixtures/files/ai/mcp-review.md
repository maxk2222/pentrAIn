# Northstar developer assistant — MCP server configuration

## mcp-servers.json

```json
{
  "servers": {
    "dev-assistant": {"tools_ns": "shared-tools"},
    "prod-assistant": {"tools_ns": "shared-tools"}
  },
  "tool_registry": {
    "repo_reader": {
      "description": "reads repository files",
      "declared_scope": "/srv/workspace",
      "fs_root": "/srv"
    },
    "ticket_api": {
      "description": "managed by integration team",
      "schema_version": "unversioned"
    }
  },
  "change_approval": {"required": false, "log": null}
}
```

## Registry change log

```
MCP-22  tool=repo_reader  description updated (no approval event attached)
MCP-21  tool=ticket_api   schema updated (approver: not recorded)
```

## Tool description (repo_reader, current)

"Reads files under the workspace and returns their contents to the
assistant for analysis."
