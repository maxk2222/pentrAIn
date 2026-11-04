# FinSight analytics agent — boundary review

## Architecture summary

- The planner, query service and report writer share one service identity.
- The query service can read every table in the reporting database.
- A policy check is performed in the user interface but not by the data service.
- The agent's action log stores the final answer but not the source records or authorization decision.

## Expected access

Analysts may query the published `quarterly_summary` view for their assigned
business unit. They may not access raw customer records or change source data.

## Review objective

Document how identity, data access, policy enforcement and audit evidence
should be separated. Do not run queries or interact with a live agent.
