# Cloudburst

> **Track**: Capstone · **Tier**: 4 · **Estimated time**: ~70 min

## Scenario

NorthBridge's perimeter is a press site with a "URL preview" feature. Their
real crown jewels live in a kubernetes cluster that was never meant to be
reachable from it. Chain the preview into the pod, and the pod into the
node. No walkthrough — this is the engagement.

## Objectives

1. Read the flag inside the `public-web` container (`edge-lfi`)
2. Prove in-pod code execution — `/tmp/.pwned` (`pod-shell`)
3. Recover the operator seed (`api-secret`)
4. Escape the cluster to the node flag (`node-flag`)
5. Document the kill chain — `/root/cloudburst-report.txt` (`chain-report`)

## Environment

- **Kali**: your attack workstation
- **edge01**: public web app on :80
- **k8s01**: a `kind` cluster — only reachable *through* edge01's preview

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `pentrAIn{...}` — submit them in the Flags panel.
- k8s01 answers nothing on your Kali — every byte must ride the SSRF.
