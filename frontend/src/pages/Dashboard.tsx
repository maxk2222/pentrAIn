import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowRight, BrainCircuit, CheckCircle2, PlayCircle, Server } from "lucide-react";
import { api, type EngineStatus, type GlobalBoardRow, type Quest, type Track } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Progress } from "@/components/ui";
import { XpHero, useXpData } from "@/components/xp";

export function DashboardPage() {
  const { activeSession } = useAppStore();
  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: () => api.get<Track[]>("/api/tracks") });
  const { data: quests } = useQuery({ queryKey: ["quests"], queryFn: () => api.get<Quest[]>("/api/quests") });
  const { data: board } = useQuery({ queryKey: ["leaderboard", "global"], queryFn: () => api.get<GlobalBoardRow[]>("/api/leaderboard") });
  const { data: engine } = useQuery({
    queryKey: ["engine-status"],
    queryFn: () => api.get<EngineStatus>("/api/engine/status"),
    refetchInterval: 30000,
  });
  const { data: profile } = useQuery({
    queryKey: ["profile"],
    queryFn: () => api.get<{ xp_total: number; track_levels: Record<string, number> }>("/api/profile"),
  });
  const engineOk = Boolean(engine?.health?.ok);
  const xp = useXpData(quests, board, tracks);

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-muted">engine {engine?.mode ?? "?"} · profile XP {profile?.xp_total ?? 0}</p>
        </div>
        <Badge variant={engineOk ? "success" : "danger"}>
          <Server className="mr-1 h-3 w-3" />
          engine {engineOk ? "online" : "offline"}
        </Badge>
      </div>

      <XpHero xp={xp.xp} xpMax={xp.xpMax} solved={xp.solved}
              total={xp.total} byTrack={xp.byTrack} compact />

      {activeSession && (
        <Card className="border-primary/40 bg-primary/5">
          <CardContent className="flex items-center justify-between p-4">
            <div className="flex items-center gap-3">
              <Activity className="h-5 w-5 animate-pulse text-primary" />
              <div>
                <div className="font-semibold">{activeSession.quest_id}</div>
                <div className="text-xs text-muted capitalize">session {activeSession.state}</div>
              </div>
            </div>
            <Link to={`/session/${activeSession.id}`}>
              <Button><PlayCircle className="h-4 w-4" /> Resume</Button>
            </Link>
          </CardContent>
        </Card>
      )}

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Tracks</h2>
          <Link to="/library" className="flex items-center gap-1 text-sm text-primary hover:underline">
            All quests <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {(tracks ?? []).map((t) => (
            <Link key={t.slug} to={`/library?track=${t.slug}`}>
              <Card className="h-full transition-colors hover:border-primary/50">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">{t.title}</CardTitle>
                    <Badge variant="accent">Lv {t.level}</Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <p className="mb-3 line-clamp-2 text-sm text-muted">{t.description}</p>
                  <div className="flex items-center gap-2 text-xs text-muted">
                    <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                    {t.solved_count}/{t.quest_count} solved
                  </div>
                  <Progress className="mt-2" value={t.quest_count ? (t.solved_count / t.quest_count) * 100 : 0} />
                </CardContent>
              </Card>
            </Link>
          ))}
          {!tracks?.length && (
            <Card className="col-span-full"><CardContent className="p-6 text-sm text-muted">
              No quest packs loaded yet — run a pack sync in Settings, or add packs to <code>content/packs</code>.
            </CardContent></Card>
          )}
        </div>
      </div>

      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <BrainCircuit className="h-4 w-4 text-primary" /><CardTitle className="text-base">Elliot</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted">
          Elliot — your AI coach (samsepi0l) — watches your command stream during sessions and adapts hints to your level.
          Set autonomy and verbosity in <Link to="/settings" className="text-primary hover:underline">Settings</Link>.
        </CardContent>
      </Card>
    </div>
  );
}
