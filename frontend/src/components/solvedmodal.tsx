import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bot, CheckCircle2, ChevronDown, Lightbulb, RotateCcw, Shield, Trophy,
  UserCheck,
} from "lucide-react";
import { api, type Attempt, type QuestDetail, type SessionFlags } from "@/lib/api";
import { Badge, Button, Card, CardContent } from "@/components/ui";
import { MarkdownView } from "@/components/markdown";
import { cn, fmtDuration } from "@/lib/utils";

/** Celebration + debrief shown when a quest is solved: animated score,
 *  breakdown, solve-style chips, per-flag ticks, the defense writeup, and
 *  the "run it back" soft-reset action. */

function gradeOf(score: number, max: number): { g: string; cls: string } {
  const r = max > 0 ? score / max : 0;
  if (r >= 0.9) return { g: "S", cls: "text-accent border-accent" };
  if (r >= 0.75) return { g: "A", cls: "text-success border-success" };
  if (r >= 0.55) return { g: "B", cls: "text-primary border-primary" };
  if (r >= 0.35) return { g: "C", cls: "text-warning border-warning" };
  return { g: "D", cls: "text-muted border-muted" };
}

function CountUp({ to }: { to: number }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const t0 = performance.now();
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / 700);
      setN(Math.round(to * (1 - (1 - k) ** 3)));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to]);
  return <>{n}</>;
}

function Row({ label, pts, minus }: { label: string; pts: number; minus?: boolean }) {
  if (!pts) return null;
  return (
    <div className="flex justify-between text-sm">
      <span className="text-muted">{label}</span>
      <span className={minus ? "text-danger" : "text-success"}>
        {minus ? "−" : "+"}{pts}
      </span>
    </div>
  );
}

export function SolvedModal({ sessionId, questId, attempt, onClose, onRestart }: {
  sessionId: number; questId: string; attempt: Attempt;
  onClose: () => void; onRestart: () => void;
}) {
  const [showDefense, setShowDefense] = useState(false);
  const { data: quest } = useQuery({
    queryKey: ["quest", questId],
    queryFn: () => api.get<QuestDetail>(`/api/quests/${questId}`),
  });
  const { data: sflags } = useQuery({
    queryKey: ["session-flags", sessionId],
    queryFn: () => api.get<SessionFlags>(`/api/sessions/${sessionId}/flags`),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const b = attempt.breakdown ?? {};
  const flagMax = (sflags?.flags ?? []).reduce((s, f) => s + f.points, 0);
  const max = flagMax + (b.time_bonus_max ?? 0);
  const { g, cls } = gradeOf(attempt.score, max);
  const a = attempt.assistance ?? {};
  const aids = (a.hints ?? 0) + (a.coach_msgs ?? 0) + (a.coach_nudges ?? 0)
    + (a.takeovers ?? 0) + (a.sheet ?? 0) + (a.chat ?? 0);
  const solo = aids === 0;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/75 p-4 overflow-y-auto">
      <Card className="my-auto w-full max-w-lg border-accent/40">
        <CardContent className="p-6">
          {/* hero */}
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <Trophy className="h-8 w-8 text-accent" />
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-widest text-muted">
                  quest cleared{(attempt.runs ?? 1) > 1 ? ` · attempt ${attempt.runs}` : ""}
                </div>
                <div className="text-lg font-bold">{quest?.title ?? questId}</div>
              </div>
            </div>
            <div className={cn("grid h-12 w-12 place-items-center rounded-lg border-2 text-2xl font-black", cls)}>
              {g}
            </div>
          </div>

          {/* score */}
          <div className="mt-4 flex items-end gap-3">
            <span className="text-5xl font-black tabular-nums text-accent">
              <CountUp to={attempt.score} />
            </span>
            <span className="pb-1.5 text-sm text-muted">
              pts · {fmtDuration(attempt.duration_s)}
            </span>
          </div>

          {/* breakdown */}
          <div className="mt-4 space-y-1 rounded-lg bg-surface-2/60 p-3">
            <Row label={`flags ${attempt.flags_found}/${attempt.flags_total}`} pts={b.flags ?? 0} />
            <Row label={`time bonus (par ${Math.round((b.par_s ?? 0) / 60)}min)`} pts={b.time_bonus ?? 0} />
            <Row label={`hints used ×${attempt.hints_used}`} pts={b.hint_cost ?? 0} minus />
            <Row label={`coach takeover ×${attempt.coach_interventions}`} pts={b.takeover_penalty ?? 0} minus />
            <div className="mt-1.5 flex justify-between border-t border-border pt-1.5 text-sm font-semibold">
              <span>total</span><span className="text-accent">{attempt.score} pts</span>
            </div>
          </div>

          {/* solve style */}
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {solo ? (
              <Badge variant="success" className="gap-1">
                <UserCheck className="h-3 w-3" /> solo clean — no assistance
              </Badge>
            ) : (
              <>
                <span className="text-[11px] uppercase tracking-wide text-muted">solve style:</span>
                {!!a.hints && <Badge variant="default" className="gap-1"><Lightbulb className="h-3 w-3" />hints ×{a.hints}</Badge>}
                {!!a.coach_msgs && <Badge variant="default" className="gap-1"><Bot className="h-3 w-3" />coach msgs ×{a.coach_msgs}</Badge>}
                {!!a.coach_nudges && <Badge variant="default" className="gap-1"><Bot className="h-3 w-3" />nudges ×{a.coach_nudges}</Badge>}
                {!!a.takeovers && <Badge variant="default" className="gap-1"><Bot className="h-3 w-3" />takeover ×{a.takeovers}</Badge>}
                {!!a.sheet && <Badge variant="default">sheet</Badge>}
                {!!a.chat && <Badge variant="default">chat</Badge>}
              </>
            )}
          </div>

          {/* flags */}
          {sflags && sflags.flags.length > 0 && (
            <div className="mt-3 space-y-1">
              {sflags.flags.map((f) => (
                <div key={f.key} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1.5">
                    <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                    {f.name}
                  </span>
                  <span className="text-muted">{f.points} pts</span>
                </div>
              ))}
            </div>
          )}

          {/* defense */}
          {quest?.defense_md && (
            <div className="mt-4 rounded-lg border border-border">
              <button
                onClick={() => setShowDefense((v) => !v)}
                className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium text-muted hover:text-foreground">
                <span className="flex items-center gap-2">
                  <Shield className="h-4 w-4" /> how to defend — the blue side
                </span>
                <ChevronDown className={cn("h-4 w-4 transition-transform", showDefense && "rotate-180")} />
              </button>
              {showDefense && (
                <div className="max-h-72 overflow-y-auto border-t border-border px-3 py-2">
                  <MarkdownView className="prose-sm">{quest.defense_md}</MarkdownView>
                </div>
              )}
            </div>
          )}

          {/* actions */}
          <div className="mt-5 flex items-center gap-2">
            <Button variant="success" onClick={onRestart} autoFocus>
              <RotateCcw className="h-4 w-4" /> run it back
            </Button>
            <Link to={`/quests/${questId}`}>
              <Button variant="secondary">leaderboard</Button>
            </Link>
            <Button variant="ghost" onClick={onClose}>close</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
