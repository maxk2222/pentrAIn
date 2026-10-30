# ADR-0002: Console access via Proxmox noVNC proxy

## Status
Accepted

## Context
The session view needs a live Kali desktop inside the browser, embedded in our UI next to the coach chat. Options: Apache Guacamole (VNC/RDP server inside the guest), Kasm containers, or the Proxmox-native noVNC console (`vncproxy` + `vncwebsocket` API endpoints).

## Decision
Use **Proxmox noVNC**: `console-proxy` (backend service) opens `vncproxy` on the engine PVE for the session's Kali VMID and bridges `vncwebsocket` to the frontend's `@novnc/novnc` canvas. A `ConsoleProvider` interface keeps Guacamole as a later option.

## Consequences
- Zero guest-side tooling required — works for every quest VM incl. Windows targets (later multi-VM views).
- Works even when the guest network is broken (console ≠ guest IP).
- The proxy sees all RFB frames → framebuffer dumps give the coach a `capture_screen` tool for free (vision-capable models).
- No clipboard/file-transfer integration in v1; Guacamole can add that later.
