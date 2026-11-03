# Soft-Schedule

> **Track**: Cloud Native · **Tier**: 1 (new track — content is hard mode) · **Estimated time**: ~50 min

## Scenario

NorthBridge migrated their shop to Kubernetes — and left a debug endpoint
in the image. You're outside the cluster; everything you get starts inside
one low-privilege pod. Escalate until you own the node.

## Objectives

1. Prove code execution inside the `shop-app` pod — drop `/tmp/.pwned`
   (`pod-shell`)
2. Read the operator seed file mounted into the pod (`api-secret`)
3. Escape to the node and read `/root/k8s-flag.txt` (`node-flag`)

## Environment

- **Kali**: your attack workstation
- **app01**: Debian host; port 80 fronts a `kind` kubernetes cluster

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `pentrAIn{...}` — submit them in the Flags panel.
- Everything reachable is a real Kubernetes API — RBAC is the vulnerability.
