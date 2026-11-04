---
id: ai-security-audit
title: AI application security — trust boundaries and safe validation
triggers: [rag, retrieval, vector store, prompt injection, mcp, model artifact, pickle]
---

## Audit workflow

1. Identify every input source: user prompt, retrieved document, tool output, model artifact and configuration.
2. Record which sources are trusted by the application and whether that trust is enforced outside the model.
3. Check tenant and authorization filters at the data-access layer, not only in prompt text.
4. Inventory tools and permissions. Each tool should have a narrow schema, explicit authorization and an auditable owner.
5. Treat model files and serialized data as untrusted. Prefer non-executable formats and verify provenance before loading.
6. Confirm findings with the lab's harmless evidence markers. Do not send secrets to external endpoints or execute untrusted artifacts.

## Remediation checks

- Keep policy decisions and access control in deterministic application code.
- Label retrieved content as untrusted data and prevent it from granting tool permissions.
- Require explicit authorization for consequential actions; log the decision and the data source.
- Restrict artifact formats, publishers, hashes and runtime permissions.
