import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Server, Square, MonitorCog } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";

interface DeploymentVm { name: string; vmid: number | null; ip: string | null; role: string }
interface DeploymentRange { range_id: string; state: string; vms: DeploymentVm[] }
interface DeploymentSession { id: number; quest_id: string; state: string; range_id: string | null; created_at: string }
interface Deployments {
  mode: string;
  ranges: DeploymentRange[];
  sessions: DeploymentSession[];
}

/** Live deployments on the engine — ranges whose VMs keep running on the host
 * even after their session ended, plus the button to tear them down. Hidden
 * entirely when nothing is deployed. */
export function DeploymentsCard() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["engine-deployments"],
    queryFn: () => api.get<Deployments>("/api/engine/deployments"),
    refetchInterval: 15000,
  });
  if (!data || (!data.ranges.length && !data.sessions.length)) return null;

  async function destroy(rangeId: string, label: string) {
    if (!confirm(`Destroy deployment ${label}? All range VMs are deleted and live sessions aborted.`)) return;
    await api.post("/api/engine/deployments/destroy", { range_id: rangeId || null });
    qc.invalidateQueries({ queryKey: ["engine-deployments"] });
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2">
        <MonitorCog className="h-4 w-4 text-primary" />
        <CardTitle className="text-base">Deployments</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {data.ranges.map((r) => (
          <div key={r.range_id || "default"} className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium">{r.range_id || "default range"}</span>
                <Badge variant={r.state.toLowerCase() === "running" ? "success" : r.state.toLowerCase() === "failed" ? "danger" : "warning"}>
                  {r.state}
                </Badge>
              </div>
              <div className="mt-1 space-y-0.5 text-xs text-muted">
                {r.vms.map((v) => (
                  <div key={v.name} className="flex items-center gap-2">
                    <Server className="h-3 w-3 shrink-0" />
                    <span className="truncate">{v.name}</span>
                    {v.vmid != null && <span>vmid {v.vmid}</span>}
                    {v.ip && <span>{v.ip}</span>}
                    <span className="capitalize">{v.role}</span>
                  </div>
                ))}
              </div>
            </div>
            <Button variant="danger" size="sm"
                    onClick={() => destroy(r.range_id, r.range_id || "the default range")}
                    title="Destroy this range and abort sessions using it">
              <Square className="h-3.5 w-3.5" /> <span className="hidden lg:inline">Destroy</span>
            </Button>
          </div>
        ))}
        {data.sessions.length > 0 && (
          <div className="border-t border-border pt-2 text-xs text-muted">
            {data.sessions.map((s) => (
              <div key={s.id} className="flex items-center justify-between py-0.5">
                <span>
                  session {s.id} · <Link className="text-primary hover:underline" to={`/session/${s.id}`}>{s.quest_id}</Link>
                </span>
                <Badge variant={s.state === "active" ? "success" : s.state === "failed" || s.state === "aborted" ? "danger" : "warning"}>
                  {s.state}
                </Badge>
              </div>
            ))}
          </div>
        )}
        {!data.ranges.length && data.sessions.length > 0 && (
          <div className="flex items-center justify-between gap-3 text-xs text-muted">
            <span>Live sessions exist but the provider reports no range.</span>
            <Button variant="danger" size="sm"
                    onClick={() => destroy("", "the default range")}>
              <Square className="h-3.5 w-3.5" /> <span className="hidden lg:inline">Destroy</span>
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
