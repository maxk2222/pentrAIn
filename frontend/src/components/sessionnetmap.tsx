/* Live session netmap — kali on the left, vlan-grouped target nodes on the
   right, with animated dashes on edges to running VMs. Self-contained SVG. */
import type { SessionVmMetric, Topology, TopologyVm } from "@/lib/api";
import { hostIp } from "@/lib/netmap";
import { chartColors as C } from "@/lib/theme";

const FLOW_CSS = "@keyframes dashflow{to{stroke-dashoffset:-24}}";

const NODE_W = 150, NODE_H = 34, PITCH = 42;
const KALI_X = 12, GROUP_X = 210, GROUP_PAD = 8, LABEL_H = 20;
const GROUP_W = NODE_W + GROUP_PAD * 2;

function statusColor(status: string | undefined): string {
  if (status === "running") return C.success;
  if (status === "error") return C.danger;
  return C.muted;
}

function Node({ x, y, name, sub, live, title, ring }: {
  x: number; y: number; name: string; sub: string;
  live?: SessionVmMetric; title: string; ring?: boolean;
}) {
  return (
    <g>
      <title>{title}</title>
      <rect x={x} y={y} width={NODE_W} height={NODE_H} rx={8}
        fill={C.surface2} stroke={ring ? C.primary : C.grid}
        strokeWidth={ring ? 1.5 : 1} />
      <circle cx={x + 12} cy={y + NODE_H / 2} r={4} fill={statusColor(live?.status)} />
      <text x={x + 22} y={y + 15} fontSize={11} fill={C.foreground}>{name}</text>
      <text x={x + 22} y={y + 27} fontSize={9} fill={C.muted}>{sub}</text>
    </g>
  );
}

export function SessionNetMap({ topology, vms, flagsSolved, flagsTotal }: {
  topology: Topology | undefined;
  vms: SessionVmMetric[];
  flagsSolved?: number; flagsTotal?: number;
}) {
  const groups = new Map<number, TopologyVm[]>();
  for (const vm of topology?.vms ?? []) {
    const vlan = vm.vlan ?? 10;
    groups.set(vlan, [...(groups.get(vlan) ?? []), vm]);
  }
  const live = new Map(vms.map((m) => [m.name, m]));

  // stacked group boxes → geometry first so the viewBox fits all vlans
  let gy = 12;
  const boxes = [...groups.keys()].sort((a, b) => a - b).map((vlan) => {
    const members = groups.get(vlan)!;
    const h = GROUP_PAD * 2 + LABEL_H + (members.length - 1) * PITCH + NODE_H;
    const box = { vlan, members, y: gy, h };
    gy += h + 12;
    return box;
  });
  const height = Math.max(150, gy);
  const width = GROUP_X + GROUP_W + 12;
  const kaliY = height / 2 - NODE_H / 2;
  const kali = live.get("kali");
  const nodeY = (g: (typeof boxes)[number], i: number) =>
    g.y + GROUP_PAD + LABEL_H + i * PITCH;
  const edge = (cy: number) => {
    const x1 = KALI_X + NODE_W, y1 = kaliY + NODE_H / 2, x2 = GROUP_X + GROUP_PAD;
    return `M ${x1} ${y1} C ${x1 + 45} ${y1}, ${x2 - 45} ${cy}, ${x2} ${cy}`;
  };
  const cpu = (m?: SessionVmMetric) =>
    m?.status === "running" ? `${((m.cpu ?? 0) * 100).toFixed(0)}% cpu` : (m?.status ?? "unknown");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img"
      aria-label="session network map">
      <style>{FLOW_CSS}</style>
      {boxes.flatMap((g) => g.members.map((vm, i) => {
        const running = live.get(vm.name)?.status === "running";
        return (
          <path key={`e-${vm.name}`} d={edge(nodeY(g, i) + NODE_H / 2)} fill="none"
            stroke={running ? C.primary : C.grid} strokeOpacity={running ? 0.7 : 1}
            strokeDasharray="6 6"
            style={running ? { animation: "dashflow 1.2s linear infinite" } : undefined} />
        );
      }))}
      {boxes.map((g) => (
        <g key={g.vlan}>
          <rect x={GROUP_X} y={g.y} width={GROUP_W} height={g.h} rx={10}
            fill="none" stroke={C.grid} />
          <text x={GROUP_X + GROUP_PAD} y={g.y + 14} fontSize={10} fill={C.muted}>
            net 10.x.{g.vlan}.0/24
          </text>
          {g.members.map((vm, i) => {
            const m = live.get(vm.name);
            return (
              <Node key={vm.name} x={GROUP_X + GROUP_PAD} y={nodeY(g, i)}
                name={vm.name} sub={cpu(m)} live={m}
                title={`${vm.name} · ${hostIp(vm.vlan, vm.ip_last_octet)} · ${m?.status ?? "unknown"}`} />
            );
          })}
        </g>
      ))}
      <Node x={KALI_X} y={kaliY} name="kali" ring live={kali}
        sub={`attacker${kali ? ` · ${cpu(kali)}` : ""}`}
        title={`kali · 10.x.10.5 · ${kali?.status ?? "unknown"}`} />
      {flagsTotal != null && (
        <text x={width - 12} y={20} fontSize={11} fill={C.accent} textAnchor="end">
          flags {flagsSolved ?? 0}/{flagsTotal}
        </text>
      )}
    </svg>
  );
}
