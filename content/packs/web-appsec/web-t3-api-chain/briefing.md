# Broken Trust

> **Track**: Web AppSec · **Tier**: 3 · **Estimated time**: ~35 min

## Scenario

NorthBridge runs a marketing site with a "URL preview" feature that fetches
link metadata server-side. The site's frontend container sits on a shared
docker network with an internal admin API that was never meant to see the
internet. Your job: get from the public page to the internal flag.

## Objectives

1. Find the file flag planted inside the `public-web` container (`web-flag`)
2. Pivot through the SSRF into the internal API and read `internal-flag`

## Environment

- **Kali**: your attack workstation
- **app01**: one Debian host, port 80 exposed. Everything else is behind it.

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `PenTrAIn{...}` — submit them in the Flags panel.
