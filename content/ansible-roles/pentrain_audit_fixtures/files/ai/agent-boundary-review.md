# FinSight analytics agent — architecture bundle

## services.yaml

```yaml
components:
  planner:        {service_account: finsight-core-sa}
  query-service:  {service_account: finsight-core-sa}
  report-writer:  {service_account: finsight-core-sa}
db_grants:
  finsight-core-sa:
    - db: reporting
      tables: ["*"]
      mode: read-write
policy_enforcement:
  location: ui-layer          # data-service trusts caller claims
audit_log:
  fields: [request_id, answer_text]
```

## Access policy (compliance doc)

Analysts may read the published `quarterly_summary` view for their
assigned business unit. Raw customer tables and write access are out of
scope for this role.

## Session trace F-88

```
planner -> query-service: SELECT * FROM customer_records WHERE unit='west'
query-service: 12,441 rows returned
report-writer: report finalized (source rows not logged)
```
