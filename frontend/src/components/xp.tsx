import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Sparkles } from "lucide-react";
import type { GlobalBoardRow, Quest, Track } from "@/lib/api";
import { Card, CardContent } from "@/components/ui";

/** rAF count-up — makes the XP number tick instead of popping in. */
export function useCountUp(target: number, ms = 1000): number {
  const [v, setV] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    const t0 = performance.now();
    const start = from.current;
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / ms);
      const eased = 1 - Math.pow(1 - p, 3);       // easeOutCubic
      const cur = Math.round(start + (target - start) * eased);
      setV(cur);
      if (p < 1) raf = requestAnimationFrame(tick);
      else from.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

/** Animated progress ring — stroke-dashoffset transitions on pct change. */
export function XpRing({ pct, size = 120, stroke = 10, track = "#232c3d",
                        color = "#22d3ee", children }: {
  pct: number; size?: number; stroke?: number;
  track?: string; color?: string; children?: React.ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const [shown, setShown] = useState(0);
  useEffect(() => {
    // defer one frame so the CSS transition actually animates 0→pct
    const id = requestAnimationFrame(() => setShown(pct));
    return () => cancelAnimationFrame(id);
  }, [pct]);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none"
                stroke={track} strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none"
                stroke={color} strokeWidth={stroke} strokeLinecap="round"
                strokeDasharray={c}
                strokeDashoffset={c * (1 - Math.min(1, Math.max(0, shown)))}
                style={{ transition: "stroke-dashoffset 1.1s cubic-bezier(.22,1,.36,1)" }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        {children}
      </div>
    </div>
  );
}

export interface TrackXp {
  slug: string; title: string;
  earned: number; max: number; solved: number; total: number;
}

/** Aggregate XP across quests: earned = Σ per-quest best scores,
 *  max = Σ quest.max_score (flag points + time bonus). */
export function useXpData(quests: Quest[] | undefined,
                          board: GlobalBoardRow[] | undefined,
                          tracks: Track[] | undefined) {
  return useMemo(() => {
    const best = new Map((board ?? []).map((r) => [r.quest_id, r.best_score]));
    const byTrack = new Map<string, TrackXp>();
    const trackTitle = new Map((tracks ?? []).map((t) => [t.slug, t.title]));
    let xp = 0, xpMax = 0, solved = 0;
    for (const q of quests ?? []) {
      const t = byTrack.get(q.track_slug) ?? {
        slug: q.track_slug,
        title: trackTitle.get(q.track_slug) ?? q.track_slug,
        earned: 0, max: 0, solved: 0, total: 0,
      };
      const b = best.get(q.id) ?? 0;
      t.earned += b;
      t.max += q.max_score ?? 0;
      t.total += 1;
      if (q.solved || b > 0) t.solved += 1;
      byTrack.set(q.track_slug, t);
      xp += b;
      xpMax += q.max_score ?? 0;
      if (q.solved || b > 0) solved += 1;
    }
    const order = new Map((tracks ?? []).map((t) => [t.slug, t.order]));
    const rows = [...byTrack.values()].sort(
      (a, b) => (order.get(a.slug) ?? 99) - (order.get(b.slug) ?? 99));
    return { xp, xpMax, solved, total: quests?.length ?? 0, byTrack: rows };
  }, [quests, board, tracks]);
}

/** XP summary hero — animated ring + count-up + per-track bars.
 *  `compact` = dashboard strip, full = leaderboard showcase. */
export function XpHero({ xp, xpMax, solved, total, byTrack, compact }: {
  xp: number; xpMax: number; solved: number; total: number;
  byTrack: TrackXp[]; compact?: boolean;
}) {
  const shownXp = useCountUp(xp);
  const pct = xpMax > 0 ? (xp / xpMax) * 100 : 0;
  const shownPct = useCountUp(pct, 1100);
  return (
    <Card className="overflow-hidden border-primary/30 bg-gradient-to-br from-primary/10 via-surface to-accent/5">
      <CardContent className={compact ? "p-4" : "p-6"}>
        <div className="flex flex-wrap items-center gap-6">
          <XpRing pct={pct / 100} size={compact ? 96 : 128}
                  stroke={compact ? 9 : 11}>
            <div className="text-center">
              <div className={`font-bold tabular-nums text-accent ${compact ? "text-xl" : "text-3xl"}`}>
                {shownPct.toFixed(0)}%
              </div>
              {!compact && <div className="text-[10px] uppercase tracking-wide text-muted">complete</div>}
            </div>
          </XpRing>
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted">
              <Sparkles className="h-3.5 w-3.5 text-warning" /> Operator XP
            </div>
            <div className={`font-bold tabular-nums leading-tight ${compact ? "text-2xl" : "text-4xl"}`}>
              {shownXp.toLocaleString()}
              <span className="ml-2 text-sm font-normal text-muted">
                / {xpMax.toLocaleString()} pts
              </span>
            </div>
            <div className="mt-1 text-xs text-muted">
              {solved} of {total} quests cleared · best score per quest summed
            </div>
          </div>
          {!compact && byTrack.length > 0 && (
            <div className="ml-auto grid min-w-64 flex-1 gap-1.5">
              {byTrack.map((t) => {
                const p = t.max > 0 ? t.earned / t.max : 0;
                return (
                  <Link key={t.slug} to={`/library?track=${t.slug}`}
                        className="group grid grid-cols-[110px_1fr_auto] items-center gap-2">
                    <span className="truncate text-xs text-muted group-hover:text-foreground">
                      {t.title}
                    </span>
                    <div className="h-2 overflow-hidden rounded-full bg-border">
                      <div className="h-full rounded-full bg-gradient-to-r from-primary to-accent transition-all duration-1000 ease-out"
                           style={{ width: `${Math.max(p * 100, t.earned > 0 ? 2 : 0)}%` }} />
                    </div>
                    <span className="w-20 text-right text-[11px] tabular-nums text-muted">
                      {t.earned.toLocaleString()}/{t.max.toLocaleString()}
                    </span>
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
