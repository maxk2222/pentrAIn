# Helio Support Agent — deployment configuration

## agent.yaml

```yaml
identity: shared-helio-svc     # used by chat-api, retrieval-worker, tools
prompt_assembly:
  - operator_policy
  - retrieved_records
  - user_message
tools:
  - name: get_ticket
    args: [ticket_id]
  - name: close_ticket
    args: [ticket_id]
    authz_hook: null
  - name: escalate
    args: [queue]
```

## Event log (last 24h)

```
EV-11 retrieval-worker: record=TT-2049 unit=finance requester_unit=support
EV-12 tool: close_ticket(ticket_id=TT-2049) -> 200 OK
EV-13 agent-log: response written; source fields: (not recorded)
```

## API doc (help page)

`close_ticket` — closes a support ticket. Intended for supervisors of the
owning business unit.
