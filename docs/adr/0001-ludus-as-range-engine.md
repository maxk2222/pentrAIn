# ADR-0001: Ludus as the range engine

## Status
Accepted

## Context
PenTRAIN needs to provision isolated, reproducible VM environments ("ranges") on Proxmox: per-quest topologies, vulnerable VMs, networks, snapshots, teardown. Building this ourselves means reimplementing VM orchestration, template builds, SDN-ish isolation and snapshot lifecycle — a large surface.

Evaluated: Ludus (AGPL), range42 (AGPL/GPL, young), Spar (very new), KYPO (OpenStack, too heavy), Crucible/TopoMojo (heavy .NET stack), own Terraform/Ansible on the Proxmox API.

## Decision
Consume **Ludus as an external service over its REST API** behind a `RangeProvider` interface (`app/ranges/`). A `MockProvider` provides the same interface for development and CI without a hypervisor.

## Consequences
- We inherit: Packer template builds (incl. `kali-x64-desktop-template`), Ansible roles per VM, per-range /24 isolation with a router VM, testing mode (snapshot + internet cutoff), VM snapshot create/rollback/remove, the GOAD provider ecosystem (`ludus-source-bsl`).
- AGPL boundary: API-only consumption, no vendored code — PenTRAIN stays Apache-2.0.
- Ludus wants a dedicated host: install it on a dedicated PVE (`mode=direct`) or inside a nested engine VM (`mode=nested`).
