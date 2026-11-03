# AskOps

> **Track**: AI Security · **Tier**: 1 (new track — content is hard mode) · **Estimated time**: ~30 min

## Scenario

NorthBridge shipped "AskOps v2", an ops-support assistant. It guards its
deployment key behind a word filter, proudly supports base64 input, and can
file admin reports through an internal tool. Three layers, three ways in.

## Objectives

1. Make AskOps reveal its system prompt — submit the deployment key inside
   (`prompt-leak`)
2. Trick it into using its privileged report tool for you (`tool-abuse`)

## Environment

- **Kali**: your attack workstation
- **app01**: Debian host, `POST /api/chat` on port 80

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `pentrAIn{...}` — submit them in the Flags panel.
- The assistant is deterministic — every refusal means *the filter saw the
  word*, not that the idea was wrong.
