import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Filter, Trophy } from "lucide-react";
import {
  api, type Assistance, type GlobalBoardRow, type Quest, type QuestLeaderboard,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Select } from "@/components/ui";
import { AID_CHIPS, AssistBadges } from "@/components/assist";
import { EmptyState } from "@/components/emptystate";
import { fmtDuration } from "@/lib/utils";

// same legacy fallbacks as AssistBadges — pre-assistance attempts only carry
// hints_used/coach_interventions, so filter and badges must agree
const aidCount = (row: {
  assistance?: Assistance; hints_used?: number; coach_interventions?: number;
}, k: string) => {
  if (k === "hints") return row.assistance?.hints ?? row.hints_used ?? 0;
  if (k === "takeovers") return row.assistance?.takeovers ?? row.coach_interventions ?? 0;
  return row.assistance?.[k as keyof Assistance] ?? 0;
};
const isSolo = (row: Parameters<typeof aidCount>[0]) =>
  AID_CHIPS.every((c) => !aidCount(row, c.key));

export function LeaderboardPage() {
  const [quest, setQuest] = useState("");
  const [aids, setAids] = useState<Set<string>>(new Set());
  const { data: quests } = useQuery({ queryKey: ["quests"], queryFn: () => api.get<Quest[]>("/api/quests") });
  const { data: global } = useQuery({ queryKey: ["leaderboard", "global"], queryFn: () => api.get<GlobalBoardRow[]>("/api/leaderboard") });
  const { data: board } = useQuery({
    queryKey: ["leaderboard", quest],
    queryFn: () => api.get<QuestLeaderboard>(`/api/quests/${quest}/leaderboard`),
    enabled: Boolean(quest),
  });

  const questTitle = (id: string) => quests?.find((q) => q.id === id)?.title ?? id;

  // solo is exclusive — picking it clears aid chips, picking an aid clears it
  const toggleAid = (k: string) => setAids((prev) => {
    if (k === "solo") return prev.has("solo") ? new Set() : new Set(["solo"]);
    const next = new Set(prev);
    next.delete("solo");
    if (next.has(k)) next.delete(k); else next.add(k);
    return next;
  });
  const matchAids = (row: Parameters<typeof aidCount>[0]) =>
    aids.size === 0 ? true
      : aids.has("solo") ? isSolo(row)
        : [...aids].every((k) => aidCount(row, k) > 0);

  const globalRows = (global ?? []).filter(matchAids);
  const historyRows = (board?.history ?? []).filter(matchAids);
  const shown = quest ? historyRows.length : globalRows.length;
  const total = quest ? (board?.history.length ?? 0) : (global?.length ?? 0);
  const filteredEmpty = aids.size > 0 && shown === 0 && total > 0;

  return (
    <div className="space-y-5 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Leaderboard</h1>
        <Select value={quest} onChange={(e) => setQuest(e.target.value)}>
          <option value="">All quests</option>
          {(quests ?? []).map((q) => <option key={q.id} value={q.id}>{q.title}</option>)}
        </Select>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {AID_CHIPS.map(({ key, icon: Icon, label, title }) => (
          <Badge key={key} variant="outline" title={title}
            onClick={() => toggleAid(key)}
            className={cn("cursor-pointer gap-1",
              aids.has(key) && "border-primary/50 bg-primary/15 text-primary")}>
            <Icon className="h-3 w-3" />{label}
          </Badge>
        ))}
        <Badge variant="outline" title="Solved with no assistance"
          onClick={() => toggleAid("solo")}
          className={cn("cursor-pointer",
            aids.has("solo") && "border-success/40 bg-success/15 text-success")}>
          solo
        </Badge>
        {aids.size > 0 && (
          <Button size="sm" variant="ghost" onClick={() => setAids(new Set())}>clear</Button>
        )}
        <span className="ml-auto text-xs text-muted">{shown} of {total} runs</span>
      </div>

      {!quest ? (
        <Card>
          <CardHeader><CardTitle className="text-base">Per-quest best scores</CardTitle></CardHeader>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-muted">
                  <th className="px-4 py-3">Quest</th><th className="px-4 py-3">Best score</th>
                  <th className="px-4 py-3">Aids used</th><th className="px-4 py-3">Attempts</th>
                </tr>
              </thead>
              <tbody>
                {globalRows.map((r) => (
                  <tr key={r.quest_id} className="border-b border-border/50 hover:bg-surface-2/40">
                    <td className="px-4 py-2.5">
                      <Link to={`/quests/${r.quest_id}`} className="text-primary hover:underline">
                        {questTitle(r.quest_id)}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 font-medium text-accent">{r.best_score}</td>
                    <td className="px-4 py-2.5"><AssistBadges attempt={r} /></td>
                    <td className="px-4 py-2.5">{r.attempts}</td>
                  </tr>
                ))}
                {!global?.length && (
                  <tr><td colSpan={4} className="px-4 py-10 text-center text-muted">
                    No completions yet — finish a quest to claim the top spot.
                  </td></tr>
                )}
              </tbody>
            </table>
            {filteredEmpty && (
              <EmptyState icon={Filter} title="No runs match these aids"
                hint="Clear the aid filters to see all runs." />
            )}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="flex-row items-center gap-2">
            <Trophy className="h-4 w-4 text-warning" />
            <CardTitle className="text-base">{questTitle(quest)}</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-muted">
                  <th className="px-4 py-3">#</th><th className="px-4 py-3">Score</th>
                  <th className="px-4 py-3">Flags</th><th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Aids used</th><th className="px-4 py-3">When</th>
                </tr>
              </thead>
              <tbody>
                {historyRows.map((a, i) => (
                  <tr key={a.id} className="border-b border-border/50">
                    <td className="px-4 py-2.5">{i === 0 && !aids.size ? <Trophy className="h-4 w-4 text-warning" /> : i + 1}</td>
                    <td className="px-4 py-2.5 font-medium text-accent">{a.score}</td>
                    <td className="px-4 py-2.5">{a.flags_found}/{a.flags_total}</td>
                    <td className="px-4 py-2.5">{fmtDuration(a.duration_s)}</td>
                    <td className="px-4 py-2.5"><AssistBadges attempt={a} /></td>
                    <td className="px-4 py-2.5 text-muted">{a.created_at ? new Date(a.created_at).toLocaleDateString() : "—"}</td>
                  </tr>
                ))}
                {!board?.history.length && (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-muted">No completions for this quest yet.</td></tr>
                )}
              </tbody>
            </table>
            {filteredEmpty && (
              <EmptyState icon={Filter} title="No runs match these aids"
                hint="Clear the aid filters to see all runs." />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
