# Northstar knowledge service — security review bundle

## Design note

The retrieval service stores documents with `tenant_id` and `classification`.
The query endpoint currently retrieves the most relevant chunks first, then
filters by tenant in the response formatter. The summarizer receives the
unfiltered chunk list.

Required outcome: a user must only receive documents authorized for their
tenant and role. Retrieval results are untrusted data, not policy.

## Tool inventory

| Tool | Current permission | Intended permission |
|---|---|---|
| `search_docs` | all tenants | current tenant only |
| `create_ticket` | any queue | user's assigned queue |
| `export_summary` | arbitrary destination | disabled for ordinary users |

## Evidence

Audit trace `RAG-17`: request tenant `blue`, retrieved chunk tenant `amber`,
formatter removed the chunk but the summarizer trace still includes its source
identifier. No external request was made.
