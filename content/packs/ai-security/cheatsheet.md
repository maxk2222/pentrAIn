# AI security review reference

## Trust boundaries

- Identify user input, retrieved content, tool output, system policy and model artifacts separately.
- Verify tenant authorization at the data source and again at each consequential tool.
- Treat retrieved content and tool descriptions as untrusted data.
- Keep policy and access-control decisions in deterministic application code.

## Model and tool governance

- Inventory tools, owners, schemas, permissions and audit records.
- Prefer data-only model formats; verify publisher, digest and provenance before use.
- Log the source documents and principal associated with each action.
- Use synthetic test records to verify allowed and denied paths.
