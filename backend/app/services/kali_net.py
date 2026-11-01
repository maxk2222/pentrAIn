"""Kali internet uplink: attach a second virtio NIC (net1) to the WAN bridge.

Only the Kali VM gets real LAN/internet — range targets stay on the
isolated vlan. net1 is hot-plugged on the running VM (config survives
soft-reset snapshots because it's part of the VM config), then the guest
brings the interface up via qemu-guest-agent: the interface is matched by
MAC so the name (eth1/ens19/…) doesn't matter, and dhclient/dhcpcd/nmcli
are tried in order — whichever the template ships wins.
"""
from __future__ import annotations

import asyncio
import re

import structlog

log = structlog.get_logger(__name__)

WAN_NET = "net1"


def target_names_for(quest) -> list[str]:
    """topology vms → 'name:octet' pins. Range IPs are deterministic
    (10.x.<vlan>.<ip_last_octet>), so the guest derives the /24 prefix from
    eth0 and writes /etc/hosts entries directly — no DNS round-trip that a
    still-booting range resolver could drop. Both the pentrain-<name>
    FQDN-ish form and the short name get pinned so either spelling works."""
    pins: list[str] = []
    for i, v in enumerate((quest.topology or {}).get("vms") or []):
        n = v.get("name")
        if not n:
            continue
        octet = v.get("ip_last_octet", 20 + i)
        pins += [f"pentrain-{n}:{octet}", f"{n}:{octet}"]
    return pins


def _net_mac(config: dict, key: str = WAN_NET) -> str | None:
    """'virtio=BC:24:11:..,bridge=vmbr0' → 'bc:24:11:..' (lower, for sysfs)."""
    raw = str(config.get(key) or "")
    m = re.search(r"=([0-9a-fA-F:]{17})", raw)
    return m.group(1).lower() if m else None


def _guest_bringup(mac: str, target_names: list[str],
                   api_host: str | None = None) -> str:
    """Shell script: find iface by MAC → link up → DHCP via NetworkManager
    first (nmcli and a manual dhclient would race into two leases), then
    drop the range gateway's default route — it outranks the LAN route
    (metric 0) and dead-ends internet traffic into testing-mode. Range
    targets stay reachable: they're on the connected /24, no default needed.

    DNS split: the range resolver NXDOMAINs anything external, and a LAN
    resolver NXDOMAINs range names — glibc stops at the first answer either
    way. So target hostnames are pinned into /etc/hosts via the range DNS
    BEFORE reordering, LAN nameservers stay first, and the range DNS sits
    last as a fallback for names the topology didn't declare.
    """
    names = " ".join(target_names)
    # the generated script MUST stay pure ASCII — guest-file-write dies on
    # wide chars inside pvedaemon (encode step), returning an opaque 500
    return f"""MAC='{mac}'
API_HOST='{api_host or ""}'
iface=$(for i in /sys/class/net/*; do
  [ "$(tr 'A-F' 'a-f' < "$i/address" 2>/dev/null)" = "$MAC" ] && basename "$i"
done)
[ -z "$iface" ] && {{ echo NOIFACE; exit 3; }}
RDNS=$(ip -4 -o addr show dev eth0 | awk '{{split($4,a,"/"); split(a[1],o,"."); \\
       print o[1]"."o[2]"."o[3]".254"; exit}}')
# stash the pre-uplink resolver for release - but only if it actually holds
# the range DNS; if a previous cycle left a LAN-only file, snapshotting it
# would bake the breakage in, so write the canonical range resolver instead
if [ -n "$RDNS" ] && [ ! -f /run/pentrain-resolv.bak ]; then
  if grep -q "nameserver $RDNS" /etc/resolv.conf 2>/dev/null; then
    cp -L /etc/resolv.conf /run/pentrain-resolv.bak 2>/dev/null || true
  else
    echo "nameserver $RDNS" > /run/pentrain-resolv.bak
  fi
fi
# pin target names into /etc/hosts - range ips are deterministic, so derive
# the /24 from eth0 and write them directly (no DNS round-trip needed)
SUB=$(ip -4 -o addr show dev eth0 | awk '{{split($4,a,"/"); split(a[1],o,"."); \\
      print o[1]"."o[2]"."o[3]; exit}}')
if [ -n "$SUB" ]; then
  grep -v ' # pentrain-wan$' /etc/hosts > /tmp/h && cat /tmp/h > /etc/hosts
  for p in {names}; do
    n=${{p%:*}}; o=${{p##*:}}
    echo "$SUB.$o $n # pentrain-wan" >> /etc/hosts
  done
fi
ip link set "$iface" up 2>/dev/null
timeout 10 nmcli device connect "$iface" >/dev/null 2>&1 || true
# poll up to 12s for a lease - NM's dhcp takes a few seconds; the dhclient
# fallback only fires if nothing materialized (avoids a duplicate lease race)
i=12; while [ $i -gt 0 ]; do
  ip -4 -o addr show "$iface" | grep -q "inet " && break; sleep 1; i=$((i-1))
done
ip -4 -o addr show "$iface" | grep -q "inet " || \\
  (timeout 15 dhclient -1 "$iface" 2>/dev/null || timeout 15 dhcpcd "$iface" 2>/dev/null || true)
OLDGW=$(ip -4 route show default dev eth0 2>/dev/null | awk '{{print $3; exit}}')
ip route del default dev eth0 2>/dev/null || true
# platform API lives on the ludus WAN bridge behind the range router — pin a
# /32 via the range gateway so telemetry/terminal keep working while the
# LAN default route owns all other egress
[ -n "$API_HOST" ] && [ -n "$RDNS" ] && \\
  ip route replace "$API_HOST"/32 via "$RDNS" dev eth0 2>/dev/null || true
# range DNS LAST - external names via LAN servers, range names via /etc/hosts
[ -n "$RDNS" ] && {{ grep -v "nameserver $RDNS" /etc/resolv.conf > /tmp/rc 2>/dev/null; \\
  echo "nameserver $RDNS" >> /tmp/rc; cat /tmp/rc > /etc/resolv.conf; }}
echo "OLDGW=$OLDGW"
ip -4 -o addr show "$iface" | awk '{{print "IP="$4}}'
echo "IF=$iface"
"""


def _guest_release(mac: str, api_host: str | None = None) -> str:
    """Down the WAN iface + restore the range gateway's default route — the
    app/telemetry host is only reachable through it once the LAN path is
    gone. Gateway derivation follows the Ludus convention (subnet .254).
    resolv.conf reverts to the pre-uplink backup (pure range DNS).

    No nmcli disconnect: NetworkManager regenerates resolv.conf async on
    disconnect and clobbers our restore — the DHCP lease is left to expire
    (harmless: the nic is hot-unplugged right after). We drop the link,
    sleep a beat for any in-flight NM rewrite, then restore + re-append the
    range nameserver as a guard."""
    return f"""MAC='{mac}'
API_HOST='{api_host or ""}'
iface=$(for i in /sys/class/net/*; do
  [ "$(tr 'A-F' 'a-f' < "$i/address" 2>/dev/null)" = "$MAC" ] && basename "$i"
done)
[ -n "$iface" ] && ip link set "$iface" down 2>/dev/null
sleep 1
RDNS=$(ip -4 -o addr show dev eth0 | awk '{{split($4,a,"/"); split(a[1],o,"."); \\
       print o[1]"."o[2]"."o[3]".254"; exit}}')
if [ -f /run/pentrain-resolv.bak ]; then
  cp -L /run/pentrain-resolv.bak /etc/resolv.conf 2>/dev/null; rm -f /run/pentrain-resolv.bak
fi
# canonical end state: ONLY the range resolver - leftover LAN nameservers are
# dead weight once the nic is gone (every lookup would stall through them)
if [ -n "$RDNS" ]; then
  grep -v '^nameserver ' /etc/resolv.conf > /tmp/rc 2>/dev/null; \\
  echo "nameserver $RDNS" >> /tmp/rc; cat /tmp/rc > /etc/resolv.conf
fi
grep -v ' # pentrain-wan$' /etc/hosts > /tmp/h 2>/dev/null && cat /tmp/h > /etc/hosts
[ -n "$API_HOST" ] && ip route del "$API_HOST"/32 2>/dev/null || true
ip route show default dev eth0 2>/dev/null | grep -q . || {{
  gw=$(ip -4 -o addr show dev eth0 | awk '{{split($4,a,"/"); split(a[1],o,"."); \\
       print o[1]"."o[2]"."o[3]".254"; exit}}')
  [ -n "$gw" ] && ip route replace default via "$gw" dev eth0 2>/dev/null
}}
true
"""


async def apply_kali_internet(engine, vmid: int, wan_bridge: str = "vmbr0",
                              target_names: list[str] | None = None,
                              api_host: str | None = None) -> dict:
    """Attach net1→wan_bridge + DHCP in guest. Returns {"ip","iface","mac"}.

    `target_names`: range hostnames to pin into /etc/hosts — the LAN
    resolver can't see them once it takes over resolv.conf.
    Idempotent — net1 already present just re-runs the guest bring-up.
    Raises RuntimeError("no DHCP lease …") when no address materializes.
    """
    pve = getattr(engine, "pve", None)
    if pve is None:
        return {"mock": True}
    # post-rollback the VM can still be booting — net1 hot-plug needs it
    # running and the guest steps need the agent
    status = (await pve.vm_status(vmid)).get("status")
    if status != "running":
        await pve.vm_start(vmid)
    if not await pve.wait_agent(vmid, 90):
        raise RuntimeError("qemu guest agent unavailable — VM still booting?")
    config = await pve.vm_config(vmid)
    if WAN_NET not in config:
        await pve.vm_config_set(vmid, **{WAN_NET: f"virtio,bridge={wan_bridge}"})
        await asyncio.sleep(2.0)          # let udev settle the hot-plugged nic
        config = await pve.vm_config(vmid)
    mac = _net_mac(config)
    if not mac:
        raise RuntimeError(f"{WAN_NET} missing after attach")
    # Long scripts as exec-args wedge the virtio QGA channel on this host —
    # write the script via guest-file-write, then exec a tiny command.
    await pve.agent_file_write(vmid, "/tmp/pentrain-netup.sh",
                               _guest_bringup(mac, target_names or [], api_host))
    r = await pve.agent_exec_sh(vmid, "timeout 55 sh /tmp/pentrain-netup.sh",
                              timeout_s=70)
    out = r.get("out") or ""
    m = re.search(r"IP=(\S+)", out)
    if not m:
        await log.awarning("kali internet: no DHCP lease",
                           vmid=vmid, out=out[:300], err=(r.get("err") or "")[:200],
                           exitcode=r.get("exitcode"))
        raise RuntimeError(f"no DHCP lease on {wan_bridge} — is a DHCP server up?")
    return {"ip": m.group(1).split("/")[0],
            "iface": (re.search(r"IF=(\S+)", out) or [None, "?"])[1],
            "mac": mac}


async def remove_kali_internet(engine, vmid: int,
                               api_host: str | None = None) -> None:
    """Release the lease + hot-unplug net1. Idempotent — no-op if absent."""
    pve = getattr(engine, "pve", None)
    if pve is None:
        return
    config = await pve.vm_config(vmid)
    mac = _net_mac(config)
    if not mac:
        return
    # detach FIRST: the hot-unplug fires a udev event that makes NetworkManager
    # regenerate resolv.conf — running the guest cleanup AFTER it means our
    # restore isn't stomped by that final rewrite
    await pve.vm_config_set(vmid, delete=WAN_NET)
    await asyncio.sleep(3.0)              # let the unplug + NM rewrite settle
    try:
        await pve.agent_file_write(vmid, "/tmp/pentrain-netdown.sh",
                                   _guest_release(mac, api_host))
        await pve.agent_exec_sh(vmid, "timeout 12 sh /tmp/pentrain-netdown.sh",
                                timeout_s=18)
    except Exception as e:  # guest agent down → config is already clean anyway
        await log.awarning("kali internet: guest release failed", error=str(e)[:120])
