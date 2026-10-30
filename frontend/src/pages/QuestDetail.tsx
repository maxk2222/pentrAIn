import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MarkdownView } from "@/components/markdown";
import { ArrowLeft, Cpu, Flag, HardDrive, Lightbulb, Lock, PlayCircle, Server, ShieldCheck, Trophy } from "lucide-react";
import { api, type QuestDetail, type QuestLeaderboard, type Session } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Tabs } from "@/components/ui";
import { DifficultyBadge } from "./Library";
import { fmtDuration } from "@/lib/utils";
import { useState } from "react";

export function QuestDetailPage() {
  const { questId } = useParams();
  const nav = useNavigate();
  const { setActiveSession } = useAppStore();
  const [tab, setTab] = useState("briefing");

  const { data: q } = useQuery({
    queryKey: ["quest", questId],
    queryFn: () => api.get<QuestDetail>(`/api/quests/${questId}`),
  });
  const { data: board } = useQuery({
    queryKey: ["leaderboard", questId],
    queryFn: () => api.get<QuestLeaderboard>(`/api/quests/${questId}/leaderboard`),
  });

  const start = useMutation({
    mutationFn: () => api.post<Session>("/api/sessions", { quest_id: questId }),
    onSuccess: (s) => { setActiveSession(s); nav(`/session/${s.id}`); },
  });

  if (!q) return <div className="p-6 text-muted">Loading…</div>;
  const vms = q.topology?.vms ?? [];
  const hints = q.hints ?? [];

  return (
    <div className="space-y-5 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link to="/library" className="mb-1 flex items-center gap-1 text-sm text-muted hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> Library
          </Link>
          <h1 className="text-2xl font-bold">{q.title}</h1>
          <div className="mt-1 flex items-center gap-2">
            <DifficultyBadge tier={q.tier} />
            {q.solved && <Badge variant="success">solved</Badge>}
            {q.best_score != null && <Badge variant="accent">best {q.best_score} pts</Badge>}
            <span className="text-sm text-muted">{q.track_slug}</span>
          </div>
        </div>
        <Button size="lg" disabled={q.locked || start.isPending} onClick={() => start.mutate()}>
          <PlayCircle className="h-5 w-5" />
          {start.isPending ? "Deploying range…" : "Start quest"}
        </Button>
      </div>

      {q.locked && (
        <Card className="border-warning/40"><CardContent className="flex items-center gap-2 p-3 text-sm text-warning">
          <Lock className="h-4 w-4" /> {q.lock_reason}
        </CardContent></Card>
      )}
      {start.isError && (
        <Card className="border-danger/40"><CardContent className="p-3 text-sm text-danger">
          {(start.error as Error).message}
        </CardContent></Card>
      )}

      <Tabs tabs={[
        { id: "briefing", label: "Briefing" },
        { id: "topology", label: `Topology (${vms.length + 1})` },
        { id: "defense", label: <span className="flex items-center gap-1"><ShieldCheck className="h-3.5 w-3.5" /> Defense</span> },
        { id: "leaderboard", label: `Leaderboard (${board?.history.length ?? 0})` },
      ]} active={tab} onChange={setTab} className="max-w-xl" />

      {tab === "briefing" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader><CardTitle className="text-base">Briefing</CardTitle></CardHeader>
            <CardContent className="prose-sm text-sm leading-relaxed text-muted [&_h1]:text-foreground [&_h2]:text-foreground [&_h3]:text-foreground [&_code]:rounded [&_code]:bg-surface-2 [&_code]:px-1 [&_code]:text-accent [&_li]:ml-4 [&_li]:list-disc">
              <MarkdownView>{q.briefing_md || q.summary}</MarkdownView>
            </CardContent>
          </Card>
          <div className="space-y-4">
            <Card>
              <CardHeader><CardTitle className="text-base">Requirements</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <Req icon={HardDrive} label="RAM" value={`${q.requirements.min_ram_gb ?? "?"} GB`} />
                <Req icon={Cpu} label="vCPUs" value={String(q.requirements.min_vcpus ?? "?")} />
                <Req icon={HardDrive} label="Disk" value={`${q.requirements.min_disk_gb ?? "?"} GB`} />
                <Req icon={Flag} label="Flags" value={String(q.flags.length)} />
              </CardContent>
            </Card>
            {hints.length > 0 && (
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Lightbulb className="h-4 w-4 text-warning" /> Hints</CardTitle></CardHeader>
                <CardContent className="space-y-1 text-sm text-muted">
                  {hints.map((h) => (
                    <div key={h.id} className="flex items-center justify-between">
                      <span>{h.id} <span className="text-xs text-muted">({h.stage})</span></span>
                      <Badge variant="warning">−{h.cost} pts</Badge>
                    </div>
                  ))}
                  <div className="pt-1 text-xs text-muted">Hints are revealed in-session via the coach or this panel.</div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

      {tab === "topology" && (
        <div className="grid gap-3 md:grid-cols-2">
          <Card className="border-primary/40">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 font-medium">
                <Server className="h-4 w-4 text-primary" /> kali
              </div>
              <div className="mt-1 text-xs text-muted">
                attacker · {q.topology.kali?.template ?? "kali-x64-desktop-template"}
              </div>
              <div className="mt-1 text-xs text-muted">
                {q.topology.kali?.ram_gb ?? 8} GB · {q.topology.kali?.cpus ?? 4} vCPU
              </div>
            </CardContent>
          </Card>
          {vms.map((vm) => (
            <Card key={vm.name}>
              <CardContent className="flex items-start justify-between p-4">
                <div>
                  <div className="flex items-center gap-2 font-medium">
                    <Server className="h-4 w-4 text-danger" /> {vm.name}
                  </div>
                  <div className="mt-1 text-xs text-muted">{vm.template}</div>
                  <div className="mt-1 text-xs text-muted">
                    {vm.ram_gb ?? "?"} GB · {vm.cpus ?? "?"} vCPU
                    {vm.ip_last_octet ? ` · 10.10.${vm.vlan ?? 10}.${vm.ip_last_octet}` : ""}
                    {vm.domain ? ` · ${vm.domain}` : ""}
                  </div>
                </div>
                {vm.roles?.length ? <Badge variant="outline">{vm.roles.join(", ")}</Badge> : null}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {tab === "defense" && (
        <Card>
          <CardHeader><CardTitle className="text-base">Defense & hardening</CardTitle></CardHeader>
          <CardContent className="prose-sm text-sm leading-relaxed text-muted [&_h1]:text-foreground [&_h2]:text-foreground [&_h3]:text-foreground [&_code]:rounded [&_code]:bg-surface-2 [&_code]:px-1 [&_code]:text-accent [&_li]:ml-4 [&_li]:list-disc">
            <MarkdownView>{q.defense_md || "No defense notes for this quest."}</MarkdownView>
          </CardContent>
        </Card>
      )}

      {tab === "leaderboard" && (
        <Card>
          {board?.best && (
            <div className="flex items-center gap-3 border-b border-border px-4 py-3 text-sm">
              <Trophy className="h-4 w-4 text-warning" />
              <span className="font-medium">Personal best:</span>
              <span className="text-accent">{board.best.score} pts</span>
              <span className="text-muted">in {fmtDuration(board.best.duration_s)}</span>
            </div>
          )}
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-muted">
                  <th className="px-4 py-3">#</th><th className="px-4 py-3">Score</th>
                  <th className="px-4 py-3">Flags</th><th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Hints</th><th className="px-4 py-3">Coach takeovers</th>
                  <th className="px-4 py-3">When</th>
                </tr>
              </thead>
              <tbody>
                {(board?.history ?? []).map((a, i) => (
                  <tr key={a.id} className="border-b border-border/50">
                    <td className="px-4 py-2.5">{i + 1}</td>
                    <td className="px-4 py-2.5 font-medium text-accent">{a.score}</td>
                    <td className="px-4 py-2.5">{a.flags_found}/{a.flags_total}</td>
                    <td className="px-4 py-2.5">{fmtDuration(a.duration_s)}</td>
                    <td className="px-4 py-2.5">{a.hints_used}</td>
                    <td className="px-4 py-2.5">{a.coach_interventions}</td>
                    <td className="px-4 py-2.5 text-muted">{a.created_at ? new Date(a.created_at).toLocaleDateString() : "—"}</td>
                  </tr>
                ))}
                {!board?.history.length && (
                  <tr><td colSpan={7} className="px-4 py-8 text-center text-muted">No completions yet — be first.</td></tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Req({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="flex items-center gap-2 text-muted"><Icon className="h-3.5 w-3.5" /> {label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
