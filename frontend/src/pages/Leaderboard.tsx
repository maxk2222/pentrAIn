import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Trophy } from "lucide-react";
import { api, type GlobalBoardRow, type Quest, type QuestLeaderboard } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, Select } from "@/components/ui";
import { AssistBadges } from "@/components/assist";
import { fmtDuration } from "@/lib/utils";

export function LeaderboardPage() {
  const [quest, setQuest] = useState("");
  const { data: quests } = useQuery({ queryKey: ["quests"], queryFn: () => api.get<Quest[]>("/api/quests") });
  const { data: global } = useQuery({ queryKey: ["leaderboard", "global"], queryFn: () => api.get<GlobalBoardRow[]>("/api/leaderboard") });
  const { data: board } = useQuery({
    queryKey: ["leaderboard", quest],
    queryFn: () => api.get<QuestLeaderboard>(`/api/quests/${quest}/leaderboard`),
    enabled: Boolean(quest),
  });

  const questTitle = (id: string) => quests?.find((q) => q.id === id)?.title ?? id;

  return (
    <div className="space-y-5 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Leaderboard</h1>
        <Select value={quest} onChange={(e) => setQuest(e.target.value)}>
          <option value="">All quests</option>
          {(quests ?? []).map((q) => <option key={q.id} value={q.id}>{q.title}</option>)}
        </Select>
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
                {(global ?? []).map((r) => (
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
                {(board?.history ?? []).map((a, i) => (
                  <tr key={a.id} className="border-b border-border/50">
                    <td className="px-4 py-2.5">{i === 0 ? <Trophy className="h-4 w-4 text-warning" /> : i + 1}</td>
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
          </CardContent>
        </Card>
      )}
    </div>
  );
}
