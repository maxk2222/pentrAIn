# Platform assurance exam — evidence bundle

## Finding A: workload identity

A public catalogue workload and an administrative import job use the same
identity. The role can modify objects outside the catalogue namespace.

## Finding B: metadata exposure

A preview worker has unrestricted outbound access and can reach the cloud
metadata network. Its identity has access to unrelated storage.

## Finding C: deployment chain

The production reconciler is broadly scoped, accepts mutable image references
and has no recorded artifact provenance. A policy exception has no owner or
expiry.

## Required report

Correlate the evidence, rank likely impact, propose immediate containment and
permanent controls, and define non-destructive verification for each finding.
