import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Cpu, HardDrive, Lock, Star } from "lucide-react";
import { api, type Quest, type Track } from "@/lib/api";
import { Badge, Card, CardContent, CardHeader, CardTitle, Tabs } from "@/components/ui";

export function LibraryPage() {
  const [params, setParams] = useSearchParams();
  const track = params.get("track") ?? "";
  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: () => api.get<Track[]>("/api/tracks") });
  const { data: quests } = useQuery({
    queryKey: ["quests", track],
    queryFn: () => api.get<Quest[]>(`/api/quests${track ? `?track=${track}` : ""}`),
  });

  return (
    <div className="space-y-5 p-6">
      <h1 className="text-2xl font-bold">Quest Library</h1>
      <Tabs
        tabs={[{ id: "", label: "All" }, ...(tracks ?? []).map((t) => ({ id: t.slug, label: t.title }))]}
        active={track}
        onChange={(id) => setParams(id ? { track: id } : {})}
      />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(quests ?? []).map((q) => <QuestCard key={q.id} q={q} />)}
        {!quests?.length && <p className="col-span-full text-sm text-muted">No quests in this selection.</p>}
      </div>
    </div>
  );
}

function QuestCard({ q }: { q: Quest }) {
  return (
    <Link to={`/quests/${q.id}`}>
      <Card className={`h-full transition-colors ${q.locked ? "opacity-60" : "hover:border-primary/50"}`}>
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-base leading-snug">{q.title}</CardTitle>
            <DifficultyBadge tier={q.tier} />
          </div>
        </CardHeader>
        <CardContent>
          <p className="mb-3 line-clamp-2 text-sm text-muted">{q.summary}</p>
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
            <span className="flex items-center gap-1"><HardDrive className="h-3 w-3" /> {q.requirements.min_ram_gb ?? "?"} GB</span>
            <span className="flex items-center gap-1"><Cpu className="h-3 w-3" /> {q.requirements.min_vcpus ?? "?"} vCPU</span>
            {q.best_score != null && (
              <span className="flex items-center gap-1 text-accent"><Star className="h-3 w-3" /> best {q.best_score}</span>
            )}
          </div>
          <div className="mt-3 flex items-center justify-between">
            {q.locked
              ? <span className="flex items-center gap-1 text-xs text-muted"><Lock className="h-3 w-3" /> {q.lock_reason || "Locked"}</span>
              : <span className="text-xs text-success">Unlocked</span>}
            {q.solved && <Badge variant="success"><CheckCircle2 className="mr-1 h-3 w-3" /> solved</Badge>}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

export function DifficultyBadge({ tier }: { tier: number }) {
  const v = tier <= 1 ? "success" : tier === 2 ? "warning" : "danger";
  return <Badge variant={v}>tier {tier}</Badge>;
}
