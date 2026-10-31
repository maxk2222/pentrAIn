# Defense notes — Report Generator

The three data sources your script aggregates are the same three a SOC
would pull for triage. The exam twist is that the *format* is the contract:
reports consumed by downstream tooling must be exact — a schema, not prose.

## Lessons baked into the scenario

- **Anonymous FTP again.** An asset CSV readable by the world is an attack
  map — it literally names the vault. Authenticate file services; treat
  inventories as sensitive metadata.
- **Status endpoints leak topology.** `status.json` publishes service
  names and uptime — recon gold. Gate diagnostics behind auth or an
  internal network, return opaque health codes publicly.
- **Auth-log visibility.** Two competing scanners in one log is the daily
  internet reality; the exam rewards *quantifying* it (counts, recency)
  instead of eyeballing — exactly what a detection rule must do.

## Detection angle

The aggregation script itself is noisy: FTP download, HTTP fetch, log
reads — a single source touching three services in sequence looks like a
triage bot *or* an intruder. Correlating multi-service access from one
source is a cheap, high-value alert.
