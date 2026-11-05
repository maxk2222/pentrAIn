# Build monitor — deployment bundle (as deployed 2026-10-28)

## docker-compose.yml (production)

```yaml
services:
  metrics-sidecar:
    image: registry.local/metrics-sidecar:1.9.3
    container_name: metrics-sidecar
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /:/host
    environment:
      SCRAPE_TARGETS: "app01:9100,app02:9100"
      LOG_LEVEL: info
```

## Service description (team wiki)

`metrics-sidecar` scrapes /metrics endpoints of the application containers
every 15s and forwards them to the central dashboard. It does not start,
stop or inspect containers as part of its function.

## Incident record DEP-19 (extract)

No exceptions were requested or approved for this deployment.
