# Packer templates

v1 uses **stock Ludus templates only** — no custom Packer builds are required:

| Used by | Ludus template |
|---|---|
| Kali attacker | `kali-x64-desktop-template` (built into Ludus) |
| Linux targets | `debian-12-x64-server-template` |
| Windows/AD (future packs) | `win2022-server-x64-template` etc. via Ludus/GOAD |

Add a `*.pkr.hcl` here only when a quest needs a baked-in toolchain that is too
slow or too fragile to provision via Ansible at deploy time (e.g. a large
toolchain, a specific vulnerable service image, snapshotted state).

When you do add one:

- name the output `pentrain-<thing>-template` so quests can reference it
- build it on the **engine** PVE (nested or direct), not the outer host
- keep the role it pairs with in `../ansible-roles/` and document the linkage
  in the quest's `quest.yaml` `topology.vms[].template` field
