import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowDownWideNarrow, Filter, Trophy } from "lucide-react";
import {
  api, type Assistance, type GlobalBoardRow, type Quest, type QuestLeaderboard,
  type Track,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Select } from "@/components/ui";
import { AID_CHIPS, AssistBadges } from "@/components/assist";
import { EmptyState } from "@/components/emptystate";
import { XpHero, useXpData } from "@/components/xp";
import { fmtDuration, scoreTitle } from "@/lib/utils";

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

type SortKey = "score" | "tier" | "title" | "attempts" | "time";
const SORTS: { key: SortKey; label: string }[] = [
  { key: "score", label: "best score" },
  { key: "tier", label: "tier" },
  { key: "title", label: "title" },
  { key: "attempts", label: "attempts" },
  { key: "time", label: "fastest" },
];
const TIERS = [0, 1, 2, 3] as const;   // 0 = all

export function LeaderboardPage() {
  const [quest, setQuest] = useState("");
  const [track, setTrack] = useState("");
  const [tier, setTier] = useState<number>(0);
  const [sort, setSort] = useState<SortKey>("score");
  const [aids, setAids] = useState<Set<string>>(new Set());
  const { data: quests } = useQuery({ queryKey: ["quests"], queryFn: () => api.get<Quest[]>("/api/quests") });
  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: () => api.get<Track[]>("/api/tracks") });
  const { data: global } = useQuery({ queryKey: ["leaderboard", "global"], queryFn: () => api.get<GlobalBoardRow[]>("/api/leaderboard") });
  const { data: board } = useQuery({
    queryKey: ["leaderboard", quest],
    queryFn: () => api.get<QuestLeaderboard>(`/api/quests/${quest}/leaderboard`),
    enabled: Boolean(quest),
  });
  const xp = useXpData(quests, global, tracks);

  const questTitle = (id: string) => quests?.find((q) => q.id === id)?.title ?? id;
  const questOf = (id: string) => quests?.find((q) => q.id === id);

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

  // grouped view: board rows joined with quest meta → track → sorted
  const grouped = useMemo(() => {
    const rows = (global ?? [])
      .map((r) => ({ ...r, quest: questOf(r.quest_id) }))
      .filter((r) => r.quest)
      .filter((r) => !track || r.quest!.track_slug === track)
      .filter((r) => !tier || r.quest!.tier === tier)
      .filter(matchAids);
    const cmp = (a: typeof rows[0], b: typeof rows[0]) =>
      sort === "score" ? b.best_score - a.best_score
        : sort === "tier" ? (a.quest!.tier - b.quest!.tier) || (b.best_score - a.best_score)
          : sort === "title" ? a.quest!.title.localeCompare(b.quest!.title)
            : sort === "attempts" ? b.attempts - a.attempts
              : (a.duration_s ?? Infinity) - (b.duration_s ?? Infinity);
    const order = new Map((tracks ?? []).map((t) => [t.slug, t.order]));
    const groups = new Map<string, typeof rows>();
    for (const r of rows) {
      const g = groups.get(r.quest!.track_slug) ?? [];
      g.push(r);
      groups.set(r.quest!.track_slug, g);
    }
    return [...groups.entries()]
      .map(([slug, rs]) => ({
        slug,
        title: (tracks ?? []).find((t) => t.slug === slug)?.title ?? slug,
        rows: rs.sort(cmp),
        earned: rs.reduce((s, r) => s + r.best_score, 0),
        max: rs.reduce((s, r) => s + (r.quest!.max_score ?? 0), 0),
      }))
      .sort((a, b) => (order.get(a.slug) ?? 99) - (order.get(b.slug) ?? 99));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [global, quests, tracks, track, tier, sort, aids]);

  const historyRows = (board?.history ?? []).filter(matchAids);
  const shown = quest ? historyRows.length : grouped.reduce((s, g) => s + g.rows.length, 0);
  const total = quest ? (board?.history.length ?? 0) : (global?.length ?? 0);
  const filteredEmpty = (aids.size > 0 || track || tier > 0) && shown === 0 && total > 0;

  const tierBadge = (t: number, exam?: boolean) => (
    <Badge variant="outline" className={cn("text-[10px]",
      exam ? "border-warning/40 text-warning" : "text-muted")}>
      {exam ? "exam" : `T${t}`}
    </Badge>
  );

  return (
    <div className="space-y-5 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Leaderboard</h1>
        <Select value={quest} onChange={(e) => setQuest(e.target.value)}>
          <option value="">All quests</option>
          {(quests ?? []).map((q) => <option key={q.id} value={q.id}>{q.title}</option>)}
        </Select>
      </div>

      <XpHero xp={xp.xp} xpMax={xp.xpMax} solved={xp.solved}
              total={xp.total} byTrack={xp.byTrack} />

      {!quest && (
        <div className="flex flex-wrap items-center gap-1.5">
          <Select value={track} onChange={(e) => setTrack(e.target.value)}
                  className="w-44">
            <option value="">All tracks</option>
            {(tracks ?? []).map((t) => <option key={t.slug} value={t.slug}>{t.title}</option>)}
          </Select>
          {TIERS.map((t) => (
            <Badge key={t} variant="outline"
              onClick={() => setTier(t)}
              className={cn("cursor-pointer",
                tier === t && "border-primary/50 bg-primary/15 text-primary")}>
              {t === 0 ? "all tiers" : `T${t}`}
            </Badge>
          ))}
          <span className="mx-1 h-4 w-px bg-border" />
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
          <span className="mx-1 h-4 w-px bg-border" />
          <ArrowDownWideNarrow className="h-3.5 w-3.5 text-muted" />
          <Select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}
                  className="w-32">
            {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </Select>
          {(aids.size > 0 || track || tier > 0) && (
            <Button size="sm" variant="ghost"
                    onClick={() => { setAids(new Set()); setTrack(""); setTier(0); }}>
              clear
            </Button>
          )}
          <span className="ml-auto text-xs text-muted">{shown} of {total} entries</span>
        </div>
      )}

      {!quest ? (
        <>
          {grouped.map((g) => (
            <Card key={g.slug} className="overflow-hidden">
              <CardHeader className="flex-row items-center gap-3 border-b border-border/60 py-3">
                <CardTitle className="text-base">{g.title}</CardTitle>
                <div className="h-1.5 w-32 overflow-hidden rounded-full bg-border">
                  <div className="h-full rounded-full bg-gradient-to-r from-primary to-accent transition-all duration-1000"
                       style={{ width: `${g.max > 0 ? (g.earned / g.max) * 100 : 0}%` }} />
                </div>
                <span className="text-xs tabular-nums text-muted">
                  {g.earned.toLocaleString()} / {g.max.toLocaleString()} XP
                </span>
                <span className="ml-auto text-xs text-muted">{g.rows.length} scored</span>
              </CardHeader>
              <CardContent className="p-0">
                <table className="w-full text-sm">
                  <tbody>
                    {g.rows.map((r, i) => (
                      <tr key={r.quest_id}
                          className="border-b border-border/50 transition-colors last:border-0 hover:bg-surface-2/40">
                        <td className="w-10 px-4 py-2.5 text-muted">
                          {i === 0 && sort === "score"
                            ? <Trophy className="h-4 w-4 text-warning" />
                            : i + 1}
                        </td>
                        <td className="px-2 py-2.5">
                          <Link to={`/quests/${r.quest_id}`} className="text-primary hover:underline">
                            {r.quest!.title}
                          </Link>
                        </td>
                        <td className="w-20 px-2 py-2.5">{tierBadge(r.quest!.tier, r.quest!.exam)}</td>
                        <td className="w-24 px-2 py-2.5 font-medium text-accent"
                            title={scoreTitle(r.breakdown)}>
                          {r.best_score}
                        </td>
                        <td className="w-20 px-2 py-2.5">
                          {r.duration_s != null ? fmtDuration(r.duration_s) : "—"}
                        </td>
                        <td className="w-28 px-2 py-2.5"><AssistBadges attempt={r} /></td>
                        <td className="w-20 px-4 py-2.5 text-right text-muted">{r.attempts}×</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          ))}
          {!grouped.length && !filteredEmpty && (
            <Card><CardContent className="px-4 py-10 text-center text-muted">
              No completions yet — finish a quest to claim the top spot.
            </CardContent></Card>
          )}
          {filteredEmpty && (
            <Card><CardContent className="p-0">
              <EmptyState icon={Filter} title="No entries match these filters"
                hint="Clear the filters to see all runs." />
            </CardContent></Card>
          )}
        </>
      ) : (
        <>
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
                      <td className="px-4 py-2.5 font-medium text-accent" title={scoreTitle(a.breakdown)}>
                        {a.score}
                      </td>
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
        </>
      )}
    </div>
  );
}
