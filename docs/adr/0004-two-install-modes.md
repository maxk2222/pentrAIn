# ADR-0004: Two install modes, endpoint-agnostic backend

## Status
Accepted

## Context
Users either have a dedicated Proxmox host for pentrAIn or want it alongside an existing homeserver PVE. Ludus takes over whichever PVE it runs on (users, networks, templates), so collocating it with unrelated VMs is unsafe; running everything nested inside one VM is the clean default.

## Decision
Installer supports `--mode nested|direct`:

- `nested` (default): create `pentrain-engine` VM on the existing PVE (nested virt, CPU=host) → Debian 12 → Proxmox VE + Ludus + `pentrain-app` VM inside. Single snapshotable appliance.
- `direct`: install Ludus on the target PVE itself (dedication preflight; `--i-know-dedicated` override).

In both modes the platform stack runs in a dedicated **`pentrain-app` VM** (docker compose) on the engine's main bridge — not docker on the PVE host (avoids iptables/nftables interference with PVE firewall + Ludus networking).

The backend only knows `PVE_API_URL` + `LUDUS_API_URL` + tokens — mode-agnostic.

## Consequences
- One codebase, two topologies; `engine.mode` recorded in settings for UI/doctor.
- Nested mode costs ~10-30% performance on Windows guests → documented; `direct` is the escape hatch.
- Outer-snapshot disaster recovery exists only in nested mode; direct mode relies on PVE backups + settings export.
