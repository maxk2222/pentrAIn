import { Link, Navigate, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { FlaskConical, Globe, PlayCircle, Terminal } from "lucide-react";
import { api, type Session } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { useState } from "react";

const FREE_QUEST_ID = "free-lab";

export function FreeLabPage() {
  const nav = useNavigate();
  const { activeSession, setActiveSession } = useAppStore();
  const [autonomy, setAutonomy] = useState(4);
  const [subagents, setSubagents] = useState(true);

  const start = useMutation({
    mutationFn: () => api.post<Session>("/api/sessions", {
      quest_id: FREE_QUEST_ID,
      autonomy_level: autonomy,
      subagents_enabled: subagents,
    }),
    onSuccess: (s) => { setActiveSession(s); nav(`/session/${s.id}`); },
  });

  // a free session is already running — hand off to its session view
  if (activeSession?.quest_id === FREE_QUEST_ID) {
    return <Navigate to={`/session/${activeSession.id}`} replace />;
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5 p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <FlaskConical className="h-6 w-6 text-primary" /> Free Lab
        </h1>
        <p className="mt-1 text-sm text-muted">
          Open Kali environment with a real internet uplink — no objectives,
          no flags, no scope. The coach runs at the autonomy level you pick
          and drops its ROE guards here; the VM is disposable (reset rebuilds).
        </p>
      </div>

      {activeSession && (
        <Card className="border-warning/40">
          <CardContent className="flex items-center justify-between gap-3 p-3 text-sm">
            <span className="text-warning">
              Session <b>{activeSession.quest_id}</b> is {activeSession.state} —
              only one session runs at a time.
            </span>
            <Link to={`/session/${activeSession.id}`}>
              <Button size="sm" variant="outline">Open session</Button>
            </Link>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle className="text-base">Coach agent</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <label className="text-sm text-muted" htmlFor="free-autonomy">
              Autonomy level
            </label>
            <select id="free-autonomy" value={autonomy}
              onChange={(e) => setAutonomy(Number(e.target.value))}
              className="rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm">
              <option value={1}>1 — observe</option>
              <option value={2}>2 — advise</option>
              <option value={3}>3 — copilot</option>
              <option value={4}>4 — full-auto</option>
            </select>
          </div>
          <div className="flex items-center justify-between gap-3">
            <label className="text-sm text-muted" htmlFor="free-subagents">
              Parallel subagents (L4)
            </label>
            <input id="free-subagents" type="checkbox" checked={subagents}
              onChange={(e) => setSubagents(e.target.checked)}
              className="h-4 w-4 accent-primary" />
          </div>
          <div className="flex items-center gap-2 text-xs text-muted">
            <Globe className="h-3.5 w-3.5" />
            Internet uplink attaches automatically at deploy.
          </div>
        </CardContent>
      </Card>

      {start.isError && (
        <Card className="border-danger/40"><CardContent className="p-3 text-sm text-danger">
          {(start.error as Error).message}
        </CardContent></Card>
      )}

      <Button size="lg" className="w-full" disabled={start.isPending}
        onClick={() => start.mutate()}>
        {start.isPending
          ? <><Terminal className="h-5 w-5" /> Deploying Kali…</>
          : <><PlayCircle className="h-5 w-5" /> Start Free Lab</>}
      </Button>
      <p className="text-center text-xs text-muted">
        Act only on targets you are authorized to test.
      </p>
    </div>
  );
}
