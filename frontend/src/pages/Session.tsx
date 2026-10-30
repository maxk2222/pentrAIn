import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen, Bot, CheckSquare, FileText, NotebookPen, PanelLeft,
  PanelRight, Play, RotateCcw, Square,
} from "lucide-react";
import { api, wsUrl, type Session, type WsEvent } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Badge, Button, Tabs } from "@/components/ui";
import { ConsoleView } from "@/components/console";
import { ChatPanel } from "@/components/chat";
import { ObjectivesPanel } from "@/components/objectives";
import { SheetPanel } from "@/components/sheet";
import { NotesPanel } from "@/components/notes";
import { LazyModal } from "@/components/lazymodal";
import { DeployLog } from "@/components/deploylog";
import { cn } from "@/lib/utils";

const TERMINAL = new Set(["solved", "aborted", "failed"]);
const PANELS_KEY = "pentrain-panels";

type Panels = { sheet: boolean; notes: boolean; chat: boolean };

const PANELS_VERSION = 2; // bump → stored prefs reset to new defaults once

function loadPanels(): Panels {
  const defaults: Panels = { sheet: false, notes: true, chat: false };
  try {
    const raw = JSON.parse(localStorage.getItem(PANELS_KEY) ?? "{}");
    if (raw.v !== PANELS_VERSION) return defaults;
    return { ...defaults, sheet: raw.sheet, notes: raw.notes, chat: raw.chat };
  } catch { return defaults; }
}

function savePanels(p: Panels) {
  localStorage.setItem(PANELS_KEY, JSON.stringify({ v: PANELS_VERSION, ...p }));
}

export function SessionPage() {
  const { sessionId: sid } = useParams();
  const sessionId = Number(sid);
  const nav = useNavigate();
  const qc = useQueryClient();
  const { setActiveSession } = useAppStore();
  const [tab, setTab] = useState("chat");
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [panels, setPanels] = useState<Panels>(loadPanels);
  const [unread, setUnread] = useState(0);
  const [lazyAsk, setLazyAsk] = useState<"sheet" | "chat" | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const { data: session, isLoading } = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.get<Session>(`/api/sessions/${sessionId}`),
    refetchInterval: (q) => (q.state.data && TERMINAL.has(q.state.data.state) ? false : 8000),
  });

  // restored-open assistance panels carry over from older sessions — the aid
  // still counts toward THIS session's solve style, so record it once on mount
  useEffect(() => {
    if (!sessionId) return;
    const p = loadPanels();
    for (const kind of ["sheet", "chat"] as const) {
      if (p[kind]) api.post(`/api/sessions/${sessionId}/assist`, { kind }).catch(() => {});
    }
  }, [sessionId]);

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

  // unread coach messages while the chat panel is collapsed — dedupe on the
  // event identity so collapsing right after a message doesn't false-flag
  const lastCounted = useRef<WsEvent | null>(null);
  useEffect(() => {
    const ev = events[events.length - 1];
    if (ev?.type === "coach_message" && !panels.chat && ev !== lastCounted.current) {
      lastCounted.current = ev;
      setUnread((u) => u + 1);
    }
  }, [events, panels.chat]);
  useEffect(() => { if (panels.chat) setUnread(0); }, [panels.chat]);

  function togglePanel(key: keyof Panels) {
    // expanding an assistance panel costs a confirmation — collapsing is free
    if (!panels[key] && key !== "notes") {
      setLazyAsk(key);
      return;
    }
    setPanels((p) => {
      const next = { ...p, [key]: !p[key] };
      savePanels(next);
      return next;
    });
  }

  function confirmLazy() {
    if (!lazyAsk) return;
    const key = lazyAsk;
    setPanels((p) => {
      const next = { ...p, [key]: true };
      savePanels(next);
      return next;
    });
    setLazyAsk(null);
    // opting into an aid is part of the attempt's solve style → leaderboard
    api.post(`/api/sessions/${sessionId}/assist`, { kind: key }).catch(() => {});
  }

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
        <div className="flex items-center gap-2">
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
          <div className="ml-1 flex items-center gap-0.5 border-l border-border pl-2">
            <PanelToggle icon={PanelLeft} label="Reference sheet"
              active={panels.sheet} onClick={() => togglePanel("sheet")} />
            <PanelToggle icon={NotebookPen} label="Notes"
              active={panels.notes} onClick={() => togglePanel("notes")} />
            <PanelToggle icon={PanelRight} label="Coach panel"
              active={panels.chat} unread={unread} onClick={() => togglePanel("chat")} />
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1">
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
          <NotesPanel sessionId={sessionId} open={panels.notes}
            onToggle={() => togglePanel("notes")} />
        </div>

        {panels.sheet ? (
          <div className="w-[340px] shrink-0 border-l border-border">
            <SheetPanel sessionId={sessionId} events={events} />
          </div>
        ) : (
          <CollapsedStrip icon={BookOpen} label="Reference"
            onClick={() => togglePanel("sheet")} />
        )}

        {panels.chat ? (
          <div className="flex w-[380px] shrink-0 flex-col border-l border-border bg-surface">
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
        ) : (
          <CollapsedStrip icon={Bot} label="Coach" unread={unread}
            onClick={() => togglePanel("chat")} />
        )}
      </div>

      {lazyAsk && (
        <LazyModal
          what={lazyAsk === "sheet" ? "the reference sheet" : "the AI coach"}
          onConfirm={confirmLazy}
          onCancel={() => setLazyAsk(null)}
        />
      )}
    </div>
  );
}

function PanelToggle({ icon: Icon, label, active, unread, onClick }: {
  icon: React.ElementType; label: string; active: boolean; unread?: number; onClick: () => void;
}) {
  return (
    <button onClick={onClick} title={`${active ? "Hide" : "Show"} ${label}`}
      className={cn("relative rounded-md p-1.5 transition-colors cursor-pointer",
        active ? "text-primary bg-primary/10" : "text-muted hover:bg-surface-2 hover:text-foreground")}>
      <Icon className="h-4 w-4" />
      {!!unread && <span className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-accent" />}
    </button>
  );
}

function CollapsedStrip({ icon: Icon, label, unread, onClick }: {
  icon: React.ElementType; label: string; unread?: number; onClick: () => void;
}) {
  return (
    <button onClick={onClick} title={`Show ${label}`}
      className="flex w-11 shrink-0 flex-col items-center gap-3 border-l border-border bg-surface py-3 text-muted hover:text-foreground cursor-pointer">
      <span className="relative">
        <Icon className="h-4 w-4" />
        {!!unread && <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-accent" />}
      </span>
      <span className="text-[10px] tracking-wide [writing-mode:vertical-rl]">{label}</span>
    </button>
  );
}
