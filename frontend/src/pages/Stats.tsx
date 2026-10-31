import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity, BarChart3, BrainCircuit, Cpu, Flag, Gauge, HardDrive,
  MemoryStick, Rocket, Server, Thermometer, Trophy, Wind,
} from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  api, type ActivityStats, type DisksOut, type EngineMetrics, type EngineStatus,
  type HostStats, type LlmUsageOut, type QuestDetail, type RrdRow,
  type SessionFlags, type SessionMetrics, type SessionMetricsHistory,
  type StorageOut,
} from "@/lib/api";
import { chartColors as C } from "@/lib/theme";
import { useAppStore } from "@/lib/store";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Progress, Tabs } from "@/components/ui";
import { SessionNetMap } from "@/components/sessionnetmap";
import { AID_CHIPS } from "@/components/assist";

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
const fmtUptime = (s: number) => {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
};
const fmtDur = (s: number) => s >= 3600 ? `${(s / 3600).toFixed(1)}h` : `${Math.round(s / 60)}min`;

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
  const { data: engine } = useQuery({
    queryKey: ["engine-status"],
    queryFn: () => api.get<EngineStatus>("/api/engine/status"),
    refetchInterval: 60000,
  });
  const { data: storage } = useQuery({
    queryKey: ["engine-storage", tf],
    queryFn: () => api.get<StorageOut>(`/api/engine/storage?timeframe=${tf}`),
    refetchInterval: 60000,
  });
  const { data: disks } = useQuery({
    queryKey: ["engine-disks"],
    queryFn: () => api.get<DisksOut>("/api/engine/disks"),
    refetchInterval: 120000,
  });
  const { data: hoststats } = useQuery({
    queryKey: ["engine-hoststats"],
    queryFn: () => api.get<HostStats>("/api/engine/hoststats"),
    refetchInterval: 30000,
  });
  const { data: activity } = useQuery({
    queryKey: ["stats-activity"],
    queryFn: () => api.get<ActivityStats>("/api/stats/activity?days=30"),
    refetchInterval: 120000,
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
    : activeSession?.state === "solved" ? "accent"
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
                  <>
                    <ResponsiveContainer width="100%" height={140}>
                      <LineChart data={(v.rows ?? []).map((r) => ({
                        ...r,
                        cpuPct: ((r.cpu ?? 0) / (r.maxcpu || 1)) * 100,
                        memPct: ((r.memused ?? 0) / (r.maxmem || 1)) * 100,
                        netinM: (r.netin ?? 0) / 1e6, netoutM: (r.netout ?? 0) / 1e6,
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
                    <ResponsiveContainer width="100%" height={60}>
                      <LineChart data={(v.rows ?? []).map((r) => ({
                        ...r,
                        netinM: (r.netin ?? 0) / 1e6, netoutM: (r.netout ?? 0) / 1e6,
                      }))}>
                        <XAxis dataKey="time" hide />
                        <YAxis tick={{ fontSize: 9 }} width={36} />
                        <Tooltip {...ttStyle}
                          labelFormatter={(t) => fmtTime(Number(t), tf)}
                          formatter={(v: unknown) => `${Number(v).toFixed(2)}MB/s`} />
                        <Line type="monotone" dataKey="netinM" name="net in"
                          stroke={C.accent} dot={false} strokeWidth={1.5} />
                        <Line type="monotone" dataKey="netoutM" name="net out"
                          stroke={C.danger} dot={false} strokeWidth={1.5} />
                      </LineChart>
                    </ResponsiveContainer>
                  </>
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
          <span className="ml-auto flex items-center gap-1.5">
            {typeof engine?.node?.uptime === "number" && (
              <Badge variant="outline" title="node uptime">
                up {fmtUptime(engine.node.uptime)}
              </Badge>
            )}
            {engine?.vms && (
              <Badge variant="outline" title="VMs running / total on the node">
                {engine.vms.running}/{engine.vms.total} VMs
              </Badge>
            )}
          </span>
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

      {/* ---- storage & disks ---- */}
      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <HardDrive className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">Storage &amp; disks</CardTitle>
          {storage && !storage.ok && <Badge variant="warning">{storage.reason}</Badge>}
        </CardHeader>
        <CardContent className="grid gap-6 lg:grid-cols-2">
          <div>
            <div className="mb-2 text-xs text-muted">storage pools</div>
            <div className="space-y-3">
              {(storage?.pools ?? []).map((p) => (
                <div key={p.storage}>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="font-medium">
                      {p.storage}
                      <span className="ml-1.5 text-muted">{p.type}{p.shared ? " · shared" : ""}</span>
                    </span>
                    <span className="text-muted">{gb(p.used ?? 0)} / {gb(p.total ?? 0)}</span>
                  </div>
                  <Progress value={p.total ? ((p.used ?? 0) / p.total) * 100 : 0} />
                  {p.trend && p.trend.length > 2 && (
                    <ResponsiveContainer width="100%" height={36}>
                      <AreaChart data={p.trend.map((r) => ({
                        ...r, pct: r.total ? ((r.used ?? 0) / r.total) * 100 : 0,
                      }))}>
                        <Area type="monotone" dataKey="pct" stroke={C.primary}
                          fill={C.primary} fillOpacity={0.2} dot={false} isAnimationActive={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                  )}
                </div>
              ))}
              {storage && !storage.pools.length && (
                <div className="text-sm text-muted">No pools reported{storage.ok ? "" : ` — ${storage.reason}`}.</div>
              )}
            </div>
          </div>
          <div>
            <div className="mb-2 text-xs text-muted">physical disks (SMART)</div>
            <div className="space-y-2">
              {(disks?.disks ?? []).map((d) => (
                <div key={d.dev} className="rounded-lg border border-border p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-medium" title={d.serial}>
                      {d.model ?? d.dev}
                    </span>
                    <Badge variant={(d.smart_health ?? d.health) === "PASSED" ? "success" : "warning"}>
                      {d.smart_health ?? d.health ?? "?"}
                    </Badge>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
                    <span>{d.size_gb ?? "?"}G</span>
                    {d.temp_c != null && (
                      <span className={d.temp_c >= 70 ? "text-danger" : d.temp_c >= 55 ? "text-warning" : ""}>
                        {d.temp_c}°C
                      </span>
                    )}
                    {d.wearout_pct != null && <span>wear {d.wearout_pct}%</span>}
                    {d.power_on_hours != null && <span>{Math.round(d.power_on_hours / 8766 * 10) / 10}y uptime</span>}
                    {d.reallocated ? <span className="text-warning">{d.reallocated} realloc</span> : null}
                    {d.smart_error && <span className="text-danger/70">smart n/a</span>}
                  </div>
                </div>
              ))}
              {disks && !disks.disks.length && (
                <div className="text-sm text-muted">No disks reported{disks.ok ? "" : ` — ${disks.reason}`}.</div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ---- thermals & gpu (host agent) ---- */}
      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <Thermometer className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">Thermals &amp; GPU</CardTitle>
          {hoststats?.ok && (
            <span className="ml-auto text-xs text-muted">host agent{hoststats.url ? ` · ${hoststats.url}` : ""}</span>
          )}
        </CardHeader>
        <CardContent>
          {hoststats?.ok ? (
            <div className="grid gap-4 lg:grid-cols-3">
              <div>
                <div className="mb-2 text-xs text-muted">
                  cpu temps{hoststats.cpu?.package_c != null ? ` — package ${hoststats.cpu.package_c}°C` : ""}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {(hoststats.cpu?.temps ?? []).map((t) => (
                    <Badge key={t.label} variant="outline"
                      className={t.c >= 80 ? "border-danger/50 text-danger" : t.c >= 65 ? "border-warning/50 text-warning" : ""}>
                      {t.label} {t.c}°C
                    </Badge>
                  ))}
                  {!hoststats.cpu?.temps?.length && <span className="text-xs text-muted">no sensors</span>}
                </div>
              </div>
              <div>
                <div className="mb-2 text-xs text-muted">gpu</div>
                {hoststats.gpu ? (
                  <div className="rounded-lg border border-border p-2.5">
                    <div className="mb-1 flex items-center justify-between text-sm">
                      <span className="font-medium">{hoststats.gpu.name}</span>
                      <span className="text-xs text-muted">{hoststats.gpu.vendor}</span>
                    </div>
                    {hoststats.gpu.util_pct != null && (
                      <>
                        <div className="mb-1 flex justify-between text-xs text-muted">
                          <span>util</span><span>{hoststats.gpu.util_pct.toFixed(0)}%</span>
                        </div>
                        <Progress value={hoststats.gpu.util_pct} />
                      </>
                    )}
                    <div className="mt-1.5 flex gap-3 text-xs text-muted">
                      {hoststats.gpu.temp_c != null && <span>{hoststats.gpu.temp_c}°C</span>}
                      {hoststats.gpu.mem_used_mb != null && (
                        <span>{hoststats.gpu.mem_used_mb.toFixed(0)}/{hoststats.gpu.mem_total_mb?.toFixed(0)}MB</span>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-muted">no GPU detected</div>
                )}
              </div>
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs text-muted">
                  <Wind className="h-3 w-3" /> fans
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {(hoststats.fans ?? []).map((f) => (
                    <Badge key={f.label} variant="outline">{f.label} {f.rpm}rpm</Badge>
                  ))}
                  {!hoststats.fans?.length && <span className="text-xs text-muted">no fans reported</span>}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-3 text-sm text-muted">
              <Gauge className="h-4 w-4 shrink-0" />
              {hoststats
                ? <>Host agent not reachable — {hoststats.reason}. Install <code className="text-foreground">pentrain-hoststats</code> on the engine host (see installer/roles/hoststats) or set <code className="text-foreground">engine.hoststats_url</code>.</>
                : "Checking for host-stats agent…"}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ---- your activity ---- */}
      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <Trophy className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">Your activity</CardTitle>
        </CardHeader>
        <CardContent>
          {activity?.ok ? (
            <div className="grid gap-5 lg:grid-cols-3">
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs text-muted">
                  <Rocket className="h-3 w-3" /> range deploys (30d)
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <Badge variant="outline">avg {fmtDur(activity.deploys.avg_s)}</Badge>
                  <Badge variant="outline">last {fmtDur(activity.deploys.last_s)}</Badge>
                  <Badge variant="outline">{activity.deploys.ready} ready</Badge>
                  {activity.deploys.failed > 0 && (
                    <Badge variant="danger">{activity.deploys.failed} failed</Badge>
                  )}
                </div>
                <div className="mb-1 mt-4 text-xs text-muted">attempts / day</div>
                {activity.attempts.length ? (
                  <ResponsiveContainer width="100%" height={110}>
                    <BarChart data={activity.attempts}>
                      <XAxis dataKey="day" tick={{ fontSize: 10 }} tickFormatter={(d) => String(d).slice(5)} />
                      <YAxis tick={{ fontSize: 10 }} width={24} allowDecimals={false} />
                      <Tooltip {...ttStyle} />
                      <Bar dataKey="count" fill={C.accent} radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <div className="text-xs text-muted">no attempts yet</div>}
              </div>
              <div>
                <div className="mb-2 text-xs text-muted">score history</div>
                {activity.scores.length > 1 ? (
                  <ResponsiveContainer width="100%" height={150}>
                    <LineChart data={activity.scores.map((s, i) => ({ ...s, i }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
                      <XAxis dataKey="i" hide />
                      <YAxis tick={{ fontSize: 10 }} width={36} domain={[0, "dataMax"]} />
                      <Tooltip {...ttStyle}
                        labelFormatter={(_, p) => p?.[0]?.payload?.quest_id ?? ""}
                        formatter={(v: unknown) => [`${v} pts`, "score"]} />
                      <Line type="monotone" dataKey="score" stroke={C.warning} dot={{ r: 2 }} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : <div className="text-xs text-muted">finish attempts to build a score history</div>}
              </div>
              <div>
                <div className="mb-2 text-xs text-muted">assistance mix (all attempts)</div>
                <AidMix aids={activity.aids} />
              </div>
            </div>
          ) : (
            <div className="text-sm text-muted">No activity data yet.</div>
          )}
        </CardContent>
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
          {(usage?.by_model?.length || usage?.by_kind?.length) ? (
            <div className="mt-4 grid gap-4 border-t border-border pt-4 lg:grid-cols-2">
              {!!usage.by_model?.length && (
                <div>
                  <div className="mb-2 text-xs text-muted">by model (7d)</div>
                  <div className="space-y-1.5">
                    {usage.by_model.map((m) => (
                      <div key={m.model} className="flex items-center justify-between gap-2 text-xs">
                        <span className="min-w-0 truncate font-mono">{m.model}</span>
                        <span className="shrink-0 text-muted">
                          {m.tokens.toLocaleString()} tok · {m.requests} req
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {!!usage.by_kind?.length && (
                <div>
                  <div className="mb-2 text-xs text-muted">by kind (7d)</div>
                  <div className="flex flex-wrap gap-1.5">
                    {usage.by_kind.map((k) => (
                      <Badge key={`${k.kind}-${k.model}`} variant="outline"
                        title={`${k.requests} requests · Ø ${k.avg_latency_ms}ms`}>
                        {k.kind} <span className="text-muted">{k.model.split("/").pop()}</span>{" "}
                        {k.tokens.toLocaleString()}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

/** Stacked horizontal bar of the assistance mix across all attempts —
 *  solo runs share the bar as the muted tail segment. */
function AidMix({ aids }: { aids: Record<string, number> }) {
  const segs = [
    ...AID_CHIPS.map((c) => ({ key: c.key, label: c.label, n: aids[c.key] ?? 0 })),
    { key: "solo", label: "solo", n: aids.solo ?? 0 },
  ].filter((s) => s.n > 0);
  const total = segs.reduce((a, s) => a + s.n, 0);
  const colors: Record<string, string> = {
    hints: C.warning, coach_msgs: C.primary, coach_nudges: C.accent,
    sheet: C.success, chat: "#a78bfa", takeovers: C.danger, solo: C.muted,
  };
  if (!total) return <div className="text-xs text-muted">no attempts yet</div>;
  return (
    <div>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface-2">
        {segs.map((s) => (
          <div key={s.key} title={`${s.label}: ${s.n}`}
            style={{ width: `${(s.n / total) * 100}%`, background: colors[s.key] }} />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {segs.map((s) => (
          <Badge key={s.key} variant="outline" className="gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: colors[s.key] }} />
            {s.label} {s.n}
          </Badge>
        ))}
      </div>
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
