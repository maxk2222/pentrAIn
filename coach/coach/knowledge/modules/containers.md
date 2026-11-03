---
id: containers
title: Containerized targets — docker walls, internal IPs, API contracts
triggers: [docker, 172.16., 172.17., container, kubernetes, api/v1]
---

# Containerized targets

- Without docker group or sudo, the docker CLI is a dead end — pivot to
  the exposed services/ports and looted configs instead of retrying
  `docker ps`/`docker exec`.
- Docker-internal IPs (172.16.0.0/12 ranges) are NOT reachable from
  Kali — reach them through the container host:
  `sshpass … ssh deploy@host 'curl -s http://172.x.y.z:port/'`.
- API enumeration: fetch `/` for the endpoint list, then probe each
  route with `?path=`/`?file=`/`?table=` style params — file-read
  parameters are the usual escape route into container loot.
- Reaching a downstream internal API? Read the CALLING application's
  source on the compromised host first — frontend/portal code holds the
  real contract (endpoint paths, auth headers, tokens). Blind-fuzzing
  endpoint names burns turns when the source already names them.
