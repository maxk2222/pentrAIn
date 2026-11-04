# Coach context — The Retrieval Boundary

## Intended path

1. Read `/opt/pentrain-audit/ai/rag-boundary.md`.
2. Trace the order of retrieval, filtering and summarization; note the evidence event.
3. Compare the listed tool permissions with the intended permissions.
4. Write `/tmp/pentrain-audit-reports/rag-boundary.md` with a finding, evidence and remediation for both issues.

## Common wrong turns

- Do not try to reach an external model or service; all evidence is local.
- A generic statement that "the prompt needs better filtering" is insufficient. Focus on server-side authorization.
- Do not copy any sensitive-looking sample data into the report.
