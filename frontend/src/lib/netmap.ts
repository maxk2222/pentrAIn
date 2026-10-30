import type { Topology, TopologyVm } from "@/lib/api";

/** Ludus subnet is 10.<range>.<vlan>.0/24 — the range octet is dynamic,
 *  so we render it as `x` instead of guessing. */
export function hostIp(vlan: number | undefined, octet: number | undefined): string {
  const v = vlan ?? 10;
  return octet ? `10.x.${v}.${octet}` : `10.x.${v}.?`;
}

function safeId(name: string): string {
  return name.replace(/[^a-zA-Z0-9_]/g, "_");
}

export function domainLabel(domain: unknown): string {
  if (domain && typeof domain === "object") {
    const d = domain as Record<string, unknown>;
    const fqdn = typeof d.fqdn === "string" ? d.fqdn.split(".")[0] : "";
    const role = typeof d.role === "string" ? d.role : "";
    return [fqdn, role].filter(Boolean).join("/");
  }
  return typeof domain === "string" ? domain : "";
}

/** quest.topology → mermaid flowchart grouped by vlan. */
export function topologyToMermaid(topo: Topology | undefined): string {
  const vms = topo?.vms ?? [];
  const groups = new Map<number, TopologyVm[]>();
  for (const vm of vms) {
    const vlan = vm.vlan ?? 10;
    groups.set(vlan, [...(groups.get(vlan) ?? []), vm]);
  }
  const vlans = [...new Set([10, ...groups.keys()])].sort((a, b) => a - b);
  const lines = [
    "flowchart LR",
    "  classDef kali fill:#1d3a5f,stroke:#3b82f6,color:#e6edf6;",
    "  classDef win fill:#3d2c1d,stroke:#d98e3b,color:#e6edf6;",
  ];
  for (const vlan of vlans) {
    lines.push(`  subgraph net${vlan}["net 10.x.${vlan}.0/24"]`);
    if (vlan === 10) {
      lines.push(`    kali["kali — attacker<br/>10.x.${vlan}.5"]`);
    }
    for (const vm of groups.get(vlan) ?? []) {
      const dom = domainLabel(vm.domain);
      const os = vm.windows || vm.domain ? "win" : "linux";
      lines.push(
        `    ${safeId(vm.name)}["${vm.name}${dom ? ` — ${dom}` : ""}<br/>${hostIp(vm.vlan, vm.ip_last_octet)} · ${os}"]`);
    }
    lines.push("  end");
  }
  lines.push("  class kali kali;");
  const winNames = vms.filter((v) => v.windows || v.domain).map((v) => safeId(v.name));
  if (winNames.length) lines.push(`  class ${winNames.join(",")} win;`);
  return lines.join("\n");
}
