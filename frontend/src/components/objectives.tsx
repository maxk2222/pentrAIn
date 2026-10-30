import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle, Flag, Terminal } from "lucide-react";
import { api, type FlagSubmitOut, type SessionFlags, type TelemetryEvent, type WsEvent } from "@/lib/api";
import { Badge, Button, Input } from "@/components/ui";

export function ObjectivesPanel({ sessionId, events }: { sessionId: number; events: WsEvent[] }) {
  const qc = useQueryClient();
  const [flag, setFlag] = useState("");
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [liveTelemetry, setLiveTelemetry] = useState<TelemetryEvent[]>([]);
  const idSeq = useRef(0); // unique ids for live events (Date.now() collides under bursts)

  const { data: progress } = useQuery({
    queryKey: ["session-flags", sessionId],
    queryFn: () => api.get<SessionFlags>(`/api/sessions/${sessionId}/flags`),
  });

  const { data: telemetry } = useQuery({
    queryKey: ["telemetry", sessionId],
    queryFn: () => api.get<TelemetryEvent[]>(`/api/sessions/${sessionId}/telemetry?limit=60`),
  });

  // live telemetry + flag results arrive over the session WS
  useEffect(() => {
    const ev = events[events.length - 1];
    if (!ev) return;
    if (ev.type === "telemetry" && ev.data) {
      const id = -(++idSeq.current); // negative → never collides with DB ids
      setLiveTelemetry((prev) => [
        ...prev.slice(-59),
        { id, kind: String(ev.data!.kind), payload: ev.data!.payload ?? {}, ts: null },
      ]);
    }
    if (ev.type === "flag" || ev.type === "solved") {
      qc.invalidateQueries({ queryKey: ["session-flags", sessionId] });
    }
  }, [events, sessionId, qc]);

  async function submitFlag() {
    const value = flag.trim();
    if (!value) return;
    setFlag("");
    try {
      const r = await api.post<FlagSubmitOut>(`/api/sessions/${sessionId}/flags`, { value });
      setResult(r.correct
        ? { ok: true, text: `+${r.points} pts${r.all_solved ? " — quest solved!" : ""}` }
        : { ok: false, text: "incorrect flag" });
      qc.invalidateQueries({ queryKey: ["session-flags", sessionId] });
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : "submission failed" });
    }
    setTimeout(() => setResult(null), 5000);
  }

  // live events may already be persisted by the time REST refetches (tab remount)
  // — drop live rows whose exact (kind, payload) is present in the REST set
  const restSigs = new Set(
    (telemetry ?? []).map((t) => `${t.kind}:${JSON.stringify(t.payload)}`));
  const live = liveTelemetry.filter(
    (t) => !restSigs.has(`${t.kind}:${JSON.stringify(t.payload)}`));
  const recent = [...(telemetry ?? []), ...live].slice(-60);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-3 py-2 text-sm font-medium">
        Objectives <Badge variant="accent" className="ml-1">{progress?.solved ?? 0}/{progress?.total ?? 0}</Badge>
      </div>
      <div className="flex-1 space-y-2 overflow-auto p-3">
        {(progress?.flags ?? []).map((f) => (
          <div key={f.key} className="flex items-start gap-2 rounded-lg bg-surface-2/50 p-2.5">
            {f.solved
              ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
              : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted" />}
            <div className="min-w-0">
              <div className={`text-sm ${f.solved ? "text-muted line-through" : ""}`}>{f.name}</div>
              <div className="mt-0.5 text-xs text-muted">{f.kind}</div>
            </div>
            <Badge variant="accent" className="ml-auto shrink-0">{f.points} pts</Badge>
          </div>
        ))}
        {!progress?.flags.length && (
          <p className="text-sm text-muted">No flags defined for this quest.</p>
        )}
      </div>

      <div className="border-t border-border">
        <div className="px-3 py-2 text-xs font-medium text-muted">Recent activity</div>
        <div className="max-h-40 space-y-1 overflow-auto px-3 pb-2">
          {recent.slice().reverse().map((t) => (
            <div key={t.id} className="flex items-center gap-1.5 font-mono text-[11px] text-muted">
              <Terminal className="h-3 w-3 shrink-0" />
              <span className="truncate">{t.kind}: {summarize(t.payload)}</span>
            </div>
          ))}
          {!recent.length && <div className="text-xs text-muted">Waiting for telemetry…</div>}
        </div>
      </div>

      <div className="flex gap-2 border-t border-border p-2">
        <Input value={flag} onChange={(e) => setFlag(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), submitFlag())}
          placeholder="pentrAIn{…}" className="font-mono" />
        <Button variant="outline" size="icon" onClick={submitFlag} disabled={!flag.trim()}>
          <Flag className="h-4 w-4" />
        </Button>
      </div>
      {result && (
        <div className={`px-3 pb-2 text-xs ${result.ok ? "text-success" : "text-danger"}`}>
          {result.text}
        </div>
      )}
    </div>
  );
}

function summarize(payload: Record<string, unknown>): string {
  return String(payload.cmd ?? payload.command ?? payload.summary ?? JSON.stringify(payload)).slice(0, 120);
}
