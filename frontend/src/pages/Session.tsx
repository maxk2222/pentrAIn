import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckSquare, FileText, Play, RotateCcw, Square } from "lucide-react";
import { api, wsUrl, type Session, type WsEvent } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Badge, Button, Tabs } from "@/components/ui";
import { ConsoleView } from "@/components/console";
import { ChatPanel } from "@/components/chat";
import { ObjectivesPanel } from "@/components/objectives";
import { DeployLog } from "@/components/deploylog";

const TERMINAL = new Set(["solved", "aborted", "failed"]);

export function SessionPage() {
  const { sessionId: sid } = useParams();
  const sessionId = Number(sid);
  const nav = useNavigate();
  const qc = useQueryClient();
  const { setActiveSession } = useAppStore();
  const [tab, setTab] = useState("chat");
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [logLines, setLogLines] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  const { data: session, isLoading } = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.get<Session>(`/api/sessions/${sessionId}`),
    refetchInterval: (q) => (q.state.data && TERMINAL.has(q.state.data.state) ? false : 8000),
  });

  // hydrate deploy log once
  useEffect(() => {
    if (!sessionId) return;
    api.get<{ log: string }>(`/api/sessions/${sessionId}/log`)
      .then((r) => setLogLines(r.log.split("\n").filter(Boolean)))
      .catch(() => {});
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;

    function connect() {
      const ws = new WebSocket(wsUrl(`/ws/session/${sessionId}`));
      wsRef.current = ws;
      ws.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data) as WsEvent;
          setEvents((prev) => [...prev.slice(-299), ev]);
          if (ev.type === "state") {
            qc.invalidateQueries({ queryKey: ["session", sessionId] });
            qc.invalidateQueries({ queryKey: ["session-flags", sessionId] });
            useAppStore.getState().loadActiveSession();
          }
          if (ev.type === "deploy_log" && ev.data?.line) {
            setLogLines((prev) => [...prev.slice(-999), String(ev.data!.line)]);
          }
        } catch { /* ignore malformed frames */ }
      };
      ws.onclose = () => {
        if (!closed) retry = setTimeout(connect, 2500); // auto-reconnect on drop
      };
    }
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [sessionId, qc]);

  async function activate() {
    await api.post(`/api/sessions/${sessionId}/activate`);
    qc.invalidateQueries({ queryKey: ["session", sessionId] });
  }

  async function reset(hard: boolean) {
    const msg = hard
      ? "HARD reset: destroy the range and redeploy from scratch?"
      : "Roll back all range VMs to the post-deploy snapshot? Flags re-randomize.";
    if (!confirm(msg)) return;
    await api.post(`/api/sessions/${sessionId}/reset`, { hard });
    qc.invalidateQueries({ queryKey: ["session", sessionId] });
  }

  async function abort() {
    if (!confirm("End this session? The range will be destroyed.")) return;
    await api.post(`/api/sessions/${sessionId}/abort`);
    setActiveSession(null);
    nav("/");
  }

  const state = session?.state;
  const consoleReady = state === "ready" || state === "active";

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <div className="flex items-center gap-3">
          <h1 className="font-semibold">{session?.quest_id ?? `session ${sessionId}`}</h1>
          {state && (
            <Badge variant={
              state === "active" ? "success"
              : state === "failed" || state === "aborted" ? "danger"
              : state === "solved" ? "accent" : "warning"}>
              {state}
            </Badge>
          )}
          {session?.error && <span className="text-xs text-danger">{session.error}</span>}
        </div>
        <div className="flex gap-2">
          {state === "ready" && (
            <Button size="sm" variant="success" onClick={activate}>
              <Play className="h-3.5 w-3.5" /> Start hacking
            </Button>
          )}
          {consoleReady && (
            <>
              <Button variant="secondary" size="sm" onClick={() => reset(false)}>
                <RotateCcw className="h-3.5 w-3.5" /> Soft reset
              </Button>
              <Button variant="secondary" size="sm" onClick={() => reset(true)}>
                Hard reset
              </Button>
            </>
          )}
          {state && !TERMINAL.has(state) && (
            <Button variant="danger" size="sm" onClick={abort}>
              <Square className="h-3.5 w-3.5" /> End session
            </Button>
          )}
          {state === "solved" && (
            <Button variant="danger" size="sm" onClick={abort}>
              <Square className="h-3.5 w-3.5" /> Tear down
            </Button>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          {consoleReady ? (
            // remount on ready_at → after a reset the stale VNC session reconnects
            <ConsoleView key={`${sessionId}-${session?.ready_at ?? ""}`}
              sessionId={sessionId} />
          ) : isLoading ? (
            <div className="grid h-full place-items-center text-sm text-muted">Loading…</div>
          ) : state === "deploying" || state === "queued" || state === "resetting" ? (
            <DeployLog lines={logLines} state={state} />
          ) : (
            <div className="grid h-full place-items-center text-sm text-muted">
              Session is {state ?? "unknown"}.
              {state === "solved" && (
                <span className="mt-2 text-accent">Quest solved — check the leaderboard.</span>
              )}
            </div>
          )}
        </div>
        <div className="flex w-[380px] flex-col border-l border-border bg-surface">
          <Tabs className="m-2" tabs={[
            { id: "chat", label: <span className="flex items-center gap-1"><Bot className="h-3.5 w-3.5" /> Coach</span> },
            { id: "objectives", label: <span className="flex items-center gap-1"><CheckSquare className="h-3.5 w-3.5" /> Objectives</span> },
            { id: "log", label: <span className="flex items-center gap-1"><FileText className="h-3.5 w-3.5" /> Log</span> },
          ]} active={tab} onChange={setTab} />
          <div className="min-h-0 flex-1">
            {tab === "chat" && <ChatPanel sessionId={sessionId} events={events} />}
            {tab === "objectives" && <ObjectivesPanel sessionId={sessionId} events={events} />}
            {tab === "log" && <DeployLog lines={logLines} state={state} fill />}
          </div>
        </div>
      </div>
    </div>
  );
}
