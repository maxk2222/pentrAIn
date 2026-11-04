# Retail cloud review — combined evidence

## Workload identity

The `catalogue-reader` identity can list and modify resources across multiple
namespaces. The application only needs read access to a namespaced inventory
view.

## Metadata and storage

A preview worker can reach the metadata network and shares credentials with
the reporting service. Storage audit records show access outside the worker's
assigned project.

## Required report

Prioritize the identity and network findings. Recommend a least-privilege
workload identity, scoped egress and synthetic verification for both allowed
and denied access.
