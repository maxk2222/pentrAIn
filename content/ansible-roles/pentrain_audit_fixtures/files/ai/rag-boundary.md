# Northstar knowledge service — system documentation

## Retrieval pipeline (services/rag/config.yaml)

```yaml
pipeline:
  - stage: retrieve
    impl: vector_search
    args: {top_k: 20}
  - stage: summarize
    impl: llm_summarizer
    input: retrieved_chunks
  - stage: render
    impl: tenant_filter
    args: {field: tenant_id, match: request.tenant}
```

## Document schema

`{doc_id, tenant_id, classification, body}` — documents carry tenant and
role tags at index time.

## Service policy (operator handbook)

Users may only receive records whose tenant_id and classification match
their session claims. Retrieved text is untrusted data.

## Query trace RAG-17

```
request: tenant=blue role=reader
retrieve: chunks=[doc:7 tenant=amber, doc:11 tenant=blue, doc:4 tenant=amber]
summarize: input=[7,11,4] -> summary refs sources 7,4
render: visible=[11]  dropped=[7,4]
```

## Tool permissions (api/tokens.py extract)

| tool | granted |
|---|---|
| search_docs | all tenants |
| create_ticket | any queue |
| export_summary | external destinations enabled |
