# Helio Support Agent — review bundle

## Architecture

The public chat service, retrieval worker and ticket tools share one service
identity. Retrieved ticket text is appended to the same prompt as operator
policy. The `close_ticket` tool accepts a ticket identifier but performs no
second authorization check.

## Audit events

- `EV-11`: retrieval worker returned a record owned by a different business unit.
- `EV-12`: agent attempted `close_ticket`; the tool service accepted the request.
- `EV-13`: no record of which retrieved source influenced the action.

## Acceptance requirements

- Enforce tenant and user authorization at each data/tool boundary.
- Keep retrieved text separate from policy and treat it as untrusted.
- Preserve a source-to-action audit trail.
- Limit tool identity to the minimum permitted operation.
