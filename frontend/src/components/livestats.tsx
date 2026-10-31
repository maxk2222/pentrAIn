import { useEffect, useId, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Cpu, MemoryStick, Network, Server, Thermometer } from "lucide-react";
import { api } from "@/lib/api";

interface Live {
  ok: boolean;
  kali?: { status?: string; cpu: number; mem: number; maxmem: number;
           netin: number; netout: number; uptime: number } | null;
  host?: { cpu: number; mem_used: number; mem_total: number;
           load1?: number | null } | null;
  temps?: { cpu_c?: number | null; gpu_c?: number | null;
            gpu_util?: number | null } | null;
}

const MAX_SAMPLES = 90; // ~4min at the 2.5s poll
const POLL_MS = 2500;

/** Tiny gradient area sparkline — hand-rolled, ~30g vs a chart lib frame. */
function Spark({ data, color, w = 74, h = 22, cap }: {
  data: number[]; color: string; w?: number; h?: number; cap?: number;
}) {
  const id = useId();
  if (data.length < 2) return <svg width={w} height={h} className="shrink-0" />;
  const top = cap ?? Math.max(...data, 1e-9) * 1.2;
  const pts = data.map((v, i) =>
    `${((i / (data.length - 1)) * w).toFixed(1)},${(h - 2 - Math.min(v, top) / top * (h - 4)).toFixed(1)}`);
  const line = `M${pts.join(" L")}`;
  return (
    <svg width={w} height={h} className="shrink-0">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.45} />
          <stop offset="100%" stopColor={color} stopOpacity={0.02} />
        </linearGradient>
      </defs>
      <path d={`${line} L${w},${h} L0,${h} Z`} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth={1.5}
        strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function Chip({ icon: Icon, label, value, sub, spark }: {
  icon: typeof Cpu; label: string; value: string; sub?: string;
  spark?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-4 w-4 shrink-0 text-white/45" />
      <div className="leading-none">
        <div className="text-[9px] font-semibold uppercase tracking-wider text-white/45">
          {label}
        </div>
        <div className="mt-1 font-mono text-xs font-semibold text-white/90">{value}</div>
        {sub && <div className="mt-0.5 font-mono text-[9px] text-white/40">{sub}</div>}
      </div>
      {spark}
    </div>
  );
}

const fmtB = (b: number) =>
  b >= 1e9 ? `${(b / 1e9).toFixed(1)}G` : b >= 1e6 ? `${(b / 1e6).toFixed(0)}M` : `${(b / 1e3).toFixed(0)}k`;
const fmtRate = (b: number) =>
  b >= 1e6 ? `${(b / 1e6).toFixed(1)}M` : b >= 1e3 ? `${(b / 1e3).toFixed(0)}k` : `${Math.max(b, 0).toFixed(0)}`;

/** Translucent telemetry strip floating over the Kali console — VM vitals,
 * engine host load and real temps, each soft-degrading independently. */
export function LiveStatsOverlay({ sessionId }: { sessionId: number }) {
  const hist = useRef<Record<string, number[]>>({});
  const prevNet = useRef<{ t: number; nin: number; nout: number } | null>(null);
  const netRate = useRef({ down: 0, up: 0 });
  const { data } = useQuery<Live>({
    queryKey: ["live", sessionId],
    queryFn: () => api.get<Live>(`/api/sessions/${sessionId}/live`),
    refetchInterval: POLL_MS,
  });

  useEffect(() => {
    if (!data?.ok) return;
    const push = (k: string, v?: number | null) => {
      if (v == null || !Number.isFinite(v)) return;
      const a = (hist.current[k] ??= []);
      a.push(v);
      if (a.length > MAX_SAMPLES) a.shift();
    };
    const k = data.kali;
    if (k) {
      push("kcpu", k.cpu);
      push("kmem", k.maxmem ? k.mem / k.maxmem : 0);
      const now = Date.now();
      if (prevNet.current) {
        const dt = Math.max((now - prevNet.current.t) / 1000, 0.5);
        netRate.current = {
          down: Math.max((k.netin - prevNet.current.nin) / dt, 0),
          up: Math.max((k.netout - prevNet.current.nout) / dt, 0),
        };
        push("knet", (netRate.current.down + netRate.current.up) / 1e6);
      }
      prevNet.current = { t: now, nin: k.netin, nout: k.netout };
    }
    if (data.host) {
      push("hcpu", data.host.cpu);
      push("hmem", data.host.mem_total ? data.host.mem_used / data.host.mem_total : 0);
    }
    if (data.temps?.cpu_c != null) push("temp", data.temps.cpu_c);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!data?.ok) return null;
  const h = hist.current;
  const k = data.kali;
  const temps = data.temps;
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex justify-center">
      <div className="pointer-events-auto mt-2 flex items-center gap-5 rounded-xl border border-white/10 bg-black/40 px-4 py-2 shadow-xl backdrop-blur-md">
        {k && (
          <>
            <Chip icon={Cpu} label="kali cpu"
              value={`${(k.cpu * 100).toFixed(0)}%`}
              spark={<Spark data={h.kcpu ?? []} cap={1} color="#4ade80" />} />
            <Chip icon={MemoryStick} label="mem"
              value={k.maxmem ? `${(k.mem / k.maxmem * 100).toFixed(0)}%` : "–"}
              sub={k.maxmem ? `${fmtB(k.mem)} / ${fmtB(k.maxmem)}` : undefined}
              spark={<Spark data={h.kmem ?? []} cap={1} color="#a78bfa" />} />
            <Chip icon={Network} label="net"
              value={`↓${fmtRate(netRate.current.down)} ↑${fmtRate(netRate.current.up)}`}
              sub="per second"
              spark={<Spark data={h.knet ?? []} color="#22d3ee" />} />
          </>
        )}
        {k && data.host && <div className="h-8 w-px bg-white/10" />}
        {data.host && (
          <Chip icon={Server} label="host cpu"
            value={`${(data.host.cpu * 100).toFixed(0)}%`}
            sub={data.host.mem_total
              ? `mem ${(data.host.mem_used / data.host.mem_total * 100).toFixed(0)}%`
              : undefined}
            spark={<Spark data={h.hcpu ?? []} cap={1} color="#fbbf24" />} />
        )}
        {temps?.cpu_c != null && (
          <Chip icon={Thermometer} label="temp"
            value={`${temps.cpu_c.toFixed(0)}°C`}
            sub={temps.gpu_c != null ? `gpu ${temps.gpu_c.toFixed(0)}°` : undefined}
            spark={<Spark data={h.temp ?? []} color="#fb7185" />} />
        )}
      </div>
    </div>
  );
}
