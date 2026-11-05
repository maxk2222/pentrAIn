# AI platform — incident evidence bundle

## A — support assistant trace

```
req: user=analyst-22 unit=support
retrieve: record=TT-2049 owner_unit=finance
summarize: input includes TT-2049
render: response delivered (record content referenced)
```

## B — tool registry record

```
tool=refund_issuer  permission changed prod (approval_event: none attached)
tool-svc log: POST /refund issuer=chat-agent user_claim=support-staff
            -> executed (no secondary check recorded)
```

## C — validation worker record

```json
{"artifact": "run-184", "loader": "generic-object-loader",
 "publisher": null, "integrity_field": null,
 "worker_env": ["/etc/registry", "/srv/projects/*/config"]}
```

## Service doc (public API)

`/refund` — issues a refund against a ticket. Restricted to billing-unit
staff per the operator handbook.
