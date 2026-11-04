/* Track skill tree — quests grouped into tier lanes with a rail + L-connector
   visual. Nodes link to quest detail; dim() fades non-matching nodes. */
import { Link } from "react-router-dom";
import {
  Bot, Bug, Building2, CheckCircle2, Cloud, Cpu, Crown, Globe, Home, Lock,
  Radar, Search, Server, Shield, Target, Terminal, Wifi,
} from "lucide-react";
import type { Quest, Track } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge, Card, CardContent, CardHeader, CardTitle, Progress } from "@/components/ui";

const TRACK_ICONS: Record<string, React.ElementType> = {
  terminal: Terminal, wifi: Wifi, radar: Radar, building: Building2,
  search: Search, target: Target, shield: Shield, cpu: Cpu, globe: Globe,
  server: Server, home: Home, cloud: Cloud, bot: Bot, crown: Crown, bug: Bug,
};

export function TrackSection({ track, quests, dim }: {
  track: Track; quests: Quest[];
  dim: (q: Quest) => boolean;   // true → node rendered dimmed by filter
}) {
  const Icon = TRACK_ICONS[track.icon] ?? Target;
  return (
    <Card>
      <CardHeader className="flex-row items-center gap-3">
        <Icon className="h-4 w-4 text-primary" />
        <CardTitle className="text-base">{track.title}</CardTitle>
        <Badge variant="accent">Lv{track.level}</Badge>
        <span className="ml-auto text-xs text-muted">
          {track.solved_count}/{track.quest_count} solved
        </span>
        <Progress className="w-24" value={track.quest_count
          ? (track.solved_count / track.quest_count) * 100 : 0} />
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <TrackTree quests={quests} dim={dim} />
      </CardContent>
    </Card>
  );
}

export function TrackTree({ quests, dim }: {
  quests: Quest[]; dim: (q: Quest) => boolean;
}) {
  const tiers = [...new Set(quests.map((q) => q.tier))].sort((a, b) => a - b);
  const maxTier = tiers.at(-1) ?? 0;
  return (
    <div className="min-w-max">
      {tiers.map((tier) => {
        const lane = quests.filter((q) => q.tier === tier);
        const regular = lane.filter((q) => !q.exam)
          .sort((a, b) => a.id.localeCompare(b.id));
        const exams = lane.filter((q) => q.exam);
        const solved = lane.filter((q) => q.solved).length;
        return (
          <div key={tier} className="flex items-stretch">
            <div className="w-16 shrink-0 py-3">
              <div className="font-bold">T{tier}</div>
              <div className="text-xs text-muted">{solved}/{lane.length}</div>
              {tier < maxTier && (
                <div className="text-[10px] text-muted">solve any →</div>
              )}
            </div>
            {/* rail: vertical L-connector on the lane edge + horizontal line
                at mid-height behind the nodes */}
            <div className="relative flex-1 border-l border-border/60 pl-4">
              <div className="absolute left-0 right-0 top-1/2 border-t border-border/60" />
              <div className="relative flex items-center gap-6 py-3">
                {regular.map((q) => <QuestNode key={q.id} q={q} dim={dim} />)}
                {exams.map((q) => (
                  <div key={q.id} className="relative shrink-0">
                    <span className="absolute -top-2.5 left-2 text-[9px] uppercase tracking-wide text-accent">
                      all
                    </span>
                    <QuestNode q={q} dim={dim} exam />
                  </div>
                ))}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function QuestNode({ q, dim, exam }: {
  q: Quest; dim: (q: Quest) => boolean; exam?: boolean;
}) {
  const state = q.solved ? "solved" : q.locked ? "locked" : "open";
  return (
    <Link to={`/quests/${q.id}`}
      className={cn(
        "relative flex h-24 w-48 shrink-0 flex-col rounded-lg border bg-surface p-2.5",
        state === "solved" && "border-success/60 bg-success/5",
        state === "open" && "border-primary/40 transition hover:-translate-y-0.5 hover:border-primary",
        state === "locked" && "opacity-50",
        exam && "border-accent/60",
        dim(q) && "opacity-25 saturate-50",
      )}>
      <div className="line-clamp-2 text-sm font-medium">{q.title}</div>
      <div className="mt-0.5 font-mono text-xs text-muted">
        {q.requirements.min_ram_gb ?? "?"}G · {q.requirements.min_vcpus ?? "?"}c
      </div>
      <div className="mt-auto flex items-center justify-between gap-1">
        {state === "solved" ? (
          <span className="flex items-center gap-1 text-xs text-success">
            <CheckCircle2 className="h-3 w-3" />
            {q.best_score != null ? `best ${q.best_score}` : "solved"}
          </span>
        ) : state === "open" ? (
          <span className="text-xs text-primary">open</span>
        ) : (
          <span className="flex min-w-0 items-center gap-1 text-xs text-muted"
            title={q.lock_reason}>
            <Lock className="h-3 w-3 shrink-0" />
            <span className="truncate">{q.lock_reason || "locked"}</span>
          </span>
        )}
        {exam && <Badge variant="accent">exam</Badge>}
      </div>
    </Link>
  );
}
