import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, BrainCircuit, Cpu, Flag, HardDrive, MemoryStick, Server } from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  api, type EngineMetrics, type LlmUsageOut, type QuestDetail, type RrdRow,
  type SessionFlags, type SessionMetrics, type SessionMetricsHistory,
} from "@/lib/api";
import { chartColors as C } from "@/lib/theme";
import { useAppStore } from "@/lib/store";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Progress, Tabs } from "@/components/ui";
import { SessionNetMap } from "@/components/sessionnetmap";

const TIMEFRAMES = ["hour", "day", "week"] as const;
const GB = 2 ** 30;

function fmtTime(epochS: number, tf: string) {
  const d = new Date(epochS * 1000);
  return tf === "hour"
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" });
}
const pct = (v: number) => `${v.toFixed(1)}%`;
const gb = (v: number) => `${(v / GB).toFixed(1)}G`;

const ttStyle = {
  contentStyle: { background: C.surface2, border: `1px solid ${C.grid}`,
                  borderRadius: 8, fontSize: 12 },
};

export function StatsPage() {
  const { activeSession } = useAppStore();
  const [tf, setTf] = useState<string>("hour");
  const { data: metrics } = useQuery({
    queryKey: ["engine-metrics", tf],
    queryFn: () => api.get<EngineMetrics>(`/api/engine/metrics?timeframe=${tf}`),
    refetchInterval: tf === "hour" ? 30000 : 60000,
  });
  const { data: vms } = useQuery({
    queryKey: ["session-metrics", activeSession?.id],
    queryFn: () => api.get<SessionMetrics>(`/api/sessions/${activeSession!.id}/metrics`),
    enabled: Boolean(activeSession?.id),
    refetchInterval: 15000,
  });
  const { data: quest } = useQuery({
    queryKey: ["quest", activeSession?.quest_id],
    queryFn: () => api.get<QuestDetail>(`/api/quests/${activeSession!.quest_id}`),
    enabled: Boolean(activeSession?.quest_id),
  });
  const { data: flags } = useQuery({
    queryKey: ["session-flags", activeSession?.id],
    queryFn: () => api.get<SessionFlags>(`/api/sessions/${activeSession!.id}/flags`),
    enabled: Boolean(activeSession?.id),
    refetchInterval: 30000,
  });
  const { data: history } = useQuery({
    queryKey: ["session-metrics-history", activeSession?.id, tf],
    queryFn: () => api.get<SessionMetricsHistory>(
      `/api/sessions/${activeSession!.id}/metrics/history?timeframe=${tf}`),
    enabled: Boolean(activeSession?.id),
    refetchInterval: 60000,
  });
  const { data: usage } = useQuery({
    queryKey: ["llm-usage"],
    queryFn: () => api.get<LlmUsageOut>("/api/llm/usage?days=7"),
    refetchInterval: 60000,
  });

  const rows = (metrics?.rows ?? []).map((r) => ({
    ...r,
    cpuPct: ((r.cpu ?? 0) / (r.maxcpu || 1)) * 100,
    memUsedG: (r.memused ?? 0) / GB, memAvailG: (r.memavailable ?? 0) / GB,
    memTotalG: (r.memtotal ?? 0) / GB,
    netinM: (r.netin ?? 0) / 1e6, netoutM: (r.netout ?? 0) / 1e6,
    iowaitPct: (r.iowait ?? 0) * 100,
  }));
  const today = usage?.days.at(-1);
  const stateVariant = activeSession?.state === "failed" ? "danger"
    : activeSession && ["ready", "active"].includes(activeSession.state)
      ? "success" : "warning";

  return (
    <div className="space-y-5 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Stats</h1>
        <Tabs
          tabs={TIMEFRAMES.map((t) => ({
            id: t, label: t === "hour" ? "1h" : t === "day" ? "24h" : "7d",
          }))}
          active={tf} onChange={setTf} />
      </div>

      {/* ---- active quest ---- */}
      {activeSession && (
        <Card>
          <CardHeader className="flex-row items-center gap-2">
            <Flag className="h-4 w-4 text-primary" />
            <CardTitle className="text-base">
              Active quest — {activeSession.quest_id}
            </CardTitle>
            <Badge variant={stateVariant}>{activeSession.state}</Badge>
            <Link to={`/session/${activeSession.id}`} className="ml-auto">
              <Button size="sm" variant="secondary">Open session →</Button>
            </Link>
          </CardHeader>
          <CardContent className="grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <SessionNetMap topology={quest?.topology} vms={vms?.vms ?? []}
                flagsSolved={flags?.solved} flagsTotal={flags?.total} />
            </div>
            <div className="space-y-3">
              {flags && (
                <div>
                  <div className="mb-1 flex justify-between text-xs text-muted">
                    <span>flags</span><span>{flags.solved}/{flags.total}</span>
                  </div>
                  <Progress value={flags.total ? (flags.solved / flags.total) * 100 : 0} />
                </div>
              )}
              {(vms?.vms ?? []).map((v) => (
                <div key={v.vmid} className="rounded-lg border border-border p-2.5">
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="text-sm font-medium">{v.name}</span>
                    <Badge variant={v.status === "running" ? "success" : "warning"}>
                      {v.role}
                    </Badge>
                  </div>
                  {v.error ? (
                    <div className="text-xs text-muted">{v.error}</div>
                  ) : (
                    <>
                      <div className="mb-1 flex justify-between text-xs text-muted">
                        <span>cpu</span><span>{((v.cpu ?? 0) * 100).toFixed(1)}%</span>
                      </div>
                      <Progress className="mb-2" value={(v.cpu ?? 0) * 100} />
                      <div className="mb-1 flex justify-between text-xs text-muted">
                        <span>ram {v.balloon ? `(balloon → ${gb(v.balloon)})` : ""}</span>
                        <span>{gb(v.mem ?? 0)} / {gb(v.maxmem ?? 0)}</span>
                      </div>
                      <Progress value={v.maxmem ? ((v.mem ?? 0) / v.maxmem) * 100 : 0} />
                    </>
                  )}
                </div>
              ))}
              {vms && !vms.vms.length && (
                <div className="text-sm text-muted">No VM metrics for this session yet.</div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ---- session vm history ---- */}
      {activeSession && history?.ok && (
        <Card>
          <CardHeader className="flex-row items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            <CardTitle className="text-base">Session VM history</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {(history.vms ?? []).map((v) => (
              <div key={v.vmid} className="rounded-lg border border-border p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-medium">{v.name}</span>
                  <span className="text-xs text-muted">{v.role} · vmid {v.vmid}</span>
                </div>
                {v.error ? (
                  <div className="text-xs text-muted">{v.error}</div>
                ) : (
                  <ResponsiveContainer width="100%" height={140}>
                    <LineChart data={(v.rows ?? []).map((r) => ({
                      ...r,
                      cpuPct: ((r.cpu ?? 0) / (r.maxcpu || 1)) * 100,
                      memPct: ((r.memused ?? 0) / (r.maxmem || 1)) * 100,
                    }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
                      <XAxis dataKey="time" tick={{ fontSize: 11 }}
                        tickFormatter={(t) => fmtTime(Number(t), tf)} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} width={36} />
                      <Tooltip {...ttStyle}
                        labelFormatter={(t) => fmtTime(Number(t), tf)}
                        formatter={(v: unknown) => pct(Number(v))} />
                      <Line type="monotone" dataKey="cpuPct" name="cpu %"
                        stroke={C.primary} dot={false} />
                      <Line type="monotone" dataKey="memPct" name="mem %"
                        stroke={C.success} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* ---- host ---- */}
      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <Server className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">Engine host</CardTitle>
          {metrics && !metrics.ok && <Badge variant="warning">{metrics.reason}</Badge>}
        </CardHeader>
        {metrics?.ok ? (
          <CardContent className="grid gap-4 lg:grid-cols-2">
            <Chart title="CPU usage" icon={<Cpu className="h-3.5 w-3.5" />}
              rows={rows} tf={tf} series={[{ key: "cpuPct", name: "cpu %", color: C.primary }]}
              fmt={pct} />
            <Chart title="Memory" icon={<MemoryStick className="h-3.5 w-3.5" />}
              rows={rows} tf={tf}
              series={[
                { key: "memUsedG", name: "used GB", color: C.success },
                { key: "memAvailG", name: "available GB", color: C.muted },
              ]} fmt={(v) => `${v.toFixed(1)}G`} />
            <Chart title="Network" icon={<Activity className="h-3.5 w-3.5" />}
              rows={rows} tf={tf} kind="line"
              series={[
                { key: "netinM", name: "in MB/s", color: C.accent },
                { key: "netoutM", name: "out MB/s", color: C.danger },
              ]} fmt={(v) => `${v.toFixed(2)}MB/s`} />
            <Chart title="Load / IO wait" icon={<HardDrive className="h-3.5 w-3.5" />}
              rows={rows} tf={tf} kind="line"
              series={[
                { key: "loadavg", name: "load", color: C.warning },
                { key: "iowaitPct", name: "iowait %", color: C.danger },
              ]} fmt={(v) => v.toFixed(2)} />
          </CardContent>
        ) : (
          <CardContent className="text-sm text-muted">
            Engine metrics unavailable{metrics ? ` — ${metrics.reason}` : " (loading…)"}.
          </CardContent>
        )}
      </Card>

      {/* ---- llm usage ---- */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <BrainCircuit className="h-4 w-4 text-primary" /> Coach LLM usage
          </CardTitle>
          {usage?.budget ? (
            <span className="text-xs text-muted">
              today {today?.tokens.toLocaleString() ?? 0} / {usage.budget.toLocaleString()} tokens
            </span>
          ) : null}
        </CardHeader>
        <CardContent>
          {usage?.budget ? (
            <div className="mb-4">
              <div className="mb-1 flex justify-between text-xs text-muted">
                <span>daily token budget</span>
                <span>{usage.budget ? Math.min(100, ((today?.tokens ?? 0) / usage.budget) * 100).toFixed(0) : 0}%</span>
              </div>
              <Progress value={usage.budget ? Math.min(100, ((today?.tokens ?? 0) / usage.budget) * 100) : 0} />
            </div>
          ) : null}
          {usage && usage.days.length ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <div className="mb-2 flex items-center gap-2 text-xs text-muted">
                  <BarChart3 className="h-3.5 w-3.5" /> tokens per day
                </div>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={usage.days}>
                    <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
                    <XAxis dataKey="day" tick={{ fontSize: 11 }} tickFormatter={(d) => String(d).slice(5)} />
                    <YAxis tick={{ fontSize: 11 }} width={60} />
                    <Tooltip {...ttStyle} />
                    <Bar dataKey="tokens" fill={C.primary} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div>
                <div className="mb-2 text-xs text-muted">avg latency (ms) · requests</div>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={usage.days}>
                    <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
                    <XAxis dataKey="day" tick={{ fontSize: 11 }} tickFormatter={(d) => String(d).slice(5)} />
                    <YAxis yAxisId="l" tick={{ fontSize: 11 }} width={60} />
                    <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11 }} width={40} />
                    <Tooltip {...ttStyle} />
                    <Line yAxisId="l" type="monotone" dataKey="avg_latency_ms" stroke={C.warning} dot={false} />
                    <Line yAxisId="r" type="monotone" dataKey="requests" stroke={C.success} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : (
            <div className="text-sm text-muted">No LLM usage recorded yet.</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Chart({ title, icon, rows, tf, series, fmt, kind = "area" }: {
  title: string; icon: React.ReactNode; rows: RrdRow[]; tf: string;
  series: { key: string; name: string; color: string }[];
  fmt: (v: number) => string; kind?: "area" | "line";
}) {
  const grid = <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />;
  const x = <XAxis dataKey="time" tick={{ fontSize: 11 }}
    tickFormatter={(t) => fmtTime(Number(t), tf)} />;
  const y = <YAxis tick={{ fontSize: 11 }} width={50} />;
  const tt = <Tooltip {...ttStyle} labelFormatter={(t) => fmtTime(Number(t), tf)}
    formatter={(v: unknown) => fmt(Number(v))} />;
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs text-muted">{icon} {title}</div>
      <ResponsiveContainer width="100%" height={160}>
        {kind === "area" ? (
          <AreaChart data={rows}>{grid}{x}{y}{tt}
            {series.map((s) => (
              <Area key={s.key} type="monotone" dataKey={s.key} name={s.name}
                stroke={s.color} fill={s.color} fillOpacity={0.25} />
            ))}
          </AreaChart>
        ) : (
          <LineChart data={rows}>{grid}{x}{y}{tt}
            {series.map((s) => (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.name}
                stroke={s.color} dot={false} />
            ))}
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
