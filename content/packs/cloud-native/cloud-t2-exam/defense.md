# Defense notes — Exam: Cloud Identity

## Assessment themes

- Separate workload identities and scope permissions to required resources.
- Deny metadata access and outbound network paths unless explicitly needed.
- Monitor access to unrelated projects and storage resources.

## Verification

Use synthetic principals to test the allowed workload action and representative
denied actions. Confirm the denied paths are logged without disclosing
credential material.
