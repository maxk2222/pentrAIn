import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen, Bot, CheckSquare, FileText, Monitor, NotebookPen, PanelBottom,
  PanelTop, Play, Plus, RotateCcw, RotateCw, Square, TerminalSquare,
  Wifi, X,
} from "lucide-react";
import { api, wsUrl, type QuestLeaderboard, type Session, type WsEvent } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Badge, Button, IconButton, Tabs } from "@/components/ui";
import { ResizeHandle } from "@/components/resizable";
import { ConsoleView } from "@/components/console";
import { TerminalView, type TermState } from "@/components/terminal";
import { ChatPanel, AutonomyToggle, SubagentsToggle } from "@/components/chat";
import { ObjectivesPanel } from "@/components/objectives";
import { SheetPanel } from "@/components/sheet";
import { NotesPanel } from "@/components/notes";
import { LazyModal } from "@/components/lazymodal";
import { LiveStatsOverlay } from "@/components/livestats";
import { DeployLog } from "@/components/deploylog";
import { cn, fmtDuration } from "@/lib/utils";

const TERMINAL = new Set(["solved", "aborted", "failed"]);
const PANELS_KEY = "pentrain-panels";
const WIDTHS_KEY = "pentrain-panel-widths";

type Panels = { progress: boolean; sheet: boolean; notes: boolean; chat: boolean };
type PanelWidths = { progress: number; sheet: number; chat: number };

const PANELS_VERSION = 3; // v>=2 prefs merge — newer keys fall back to defaults
const WIDTH_DEFAULTS: PanelWidths = { progress: 300, sheet: 340, chat: 380 };
const WIDTH_MIN = 240, WIDTH_MAX = 720;

function loadPanels(): Panels {
  const defaults: Panels = { progress: true, sheet: false, notes: true, chat: false };
  try {
    const raw = JSON.parse(localStorage.getItem(PANELS_KEY) ?? "{}");
    // v2+ prefs carry over — keys added later fall back to defaults
    if (!(raw.v >= 2)) return defaults;
    for (const k of Object.keys(defaults) as (keyof Panels)[]) {
      if (typeof raw[k] === "boolean") defaults[k] = raw[k];
    }
    return defaults;
  } catch { return defaults; }
}

function savePanels(p: Panels) {
  localStorage.setItem(PANELS_KEY, JSON.stringify({ v: PANELS_VERSION, ...p }));
}

const clampWidth = (px: number) => Math.min(WIDTH_MAX, Math.max(WIDTH_MIN, Math.round(px)));

// ---------- browser terminal tabs ----------
type TermTab = { chan: string; title: string; docked: boolean };
type TermPrefs = { tabs: TermTab[]; active: string; dockH: number };
const DOCK_H_DEFAULT = 260, DOCK_H_MIN = 140, DOCK_H_MAX = 600;

function loadTerms(sessionId: number): TermPrefs {
  const d: TermPrefs = { tabs: [], active: "desktop", dockH: DOCK_H_DEFAULT };
  try {
    const raw = JSON.parse(localStorage.getItem(`pentrain-terms-${sessionId}`) ?? "{}");
    if (Array.isArray(raw.tabs)) {
      for (const t of raw.tabs) {
        if (typeof t?.chan === "string" && /^[a-z0-9-]{4,40}$/.test(t.chan)) {
          d.tabs.push({
            chan: t.chan,
            title: typeof t.title === "string" ? t.title.slice(0, 24) : "Term",
            docked: !!t.docked,
          });
        }
      }
    }
    if (typeof raw.active === "string") d.active = raw.active;
    if (typeof raw.dockH === "number")
      d.dockH = Math.min(DOCK_H_MAX, Math.max(DOCK_H_MIN, raw.dockH));
  } catch { /* defaults */ }
  if (d.active !== "desktop" && !d.tabs.some((t) => t.chan === d.active && !t.docked))
    d.active = "desktop";
  return d;
}

function saveTerms(sessionId: number, p: TermPrefs) {
  localStorage.setItem(`pentrain-terms-${sessionId}`, JSON.stringify(p));
}

const TERM_DOT: Record<TermState, string> = {
  live: "text-success", waiting: "text-warning",
  connecting: "text-muted", exited: "text-warning", closed: "text-danger",
};

function loadWidths(): PanelWidths {
  const w = { ...WIDTH_DEFAULTS };
  try {
    const raw = JSON.parse(localStorage.getItem(WIDTHS_KEY) ?? "{}");
    for (const k of Object.keys(w) as (keyof PanelWidths)[]) {
      if (typeof raw[k] === "number") w[k] = clampWidth(raw[k]);
    }
  } catch { /* fall back to defaults */ }
  return w;
}

export function SessionPage() {
  const { sessionId: sid } = useParams();
  const sessionId = Number(sid);
  const nav = useNavigate();
  const qc = useQueryClient();
  const { setActiveSession } = useAppStore();
  const [progressTab, setProgressTab] = useState("objectives");
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [panels, setPanels] = useState<Panels>(loadPanels);
  const [widths, setWidths] = useState<PanelWidths>(loadWidths);
  const [unread, setUnread] = useState(0);
  const [lazyAsk, setLazyAsk] = useState<"sheet" | "chat" | null>(null);
  const [termPrefs, setTermPrefs] = useState<TermPrefs>(() => loadTerms(sessionId));
  const [termStates, setTermStates] = useState<Record<string, TermState>>({});
  const [activeDock, setActiveDock] = useState<string | null>(null);

  // navigating /session/1 → /session/2 doesn't remount the page — the
  // useState initializer would leak the other session's tabs without this
  useEffect(() => {
    setTermPrefs(loadTerms(sessionId));
    setTermStates({});
    setActiveDock(null);
  }, [sessionId]);
  const wsRef = useRef<WebSocket | null>(null);

  const { data: session, isLoading } = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.get<Session>(`/api/sessions/${sessionId}`),
    refetchInterval: (q) => (q.state.data && TERMINAL.has(q.state.data.state) ? false : 8000),
  });

  // solved → pull this session's attempt for the score breakdown incl. time
  const { data: board } = useQuery({
    queryKey: ["leaderboard", session?.quest_id],
    queryFn: () => api.get<QuestLeaderboard>(`/api/quests/${session?.quest_id}/leaderboard`),
    enabled: session?.state === "solved" && Boolean(session?.quest_id),
  });
  const attempt = board?.history.find((a) => a.session_id === sessionId);

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
          if (ev.type === "state" || ev.type === "autonomy"
              || ev.type === "subagents") {
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
  // event identity so collapsing right after a message doesn't false-flag.
  // Worker-tagged messages (meta.agent) feed their own chips, not this dot.
  const lastCounted = useRef<WsEvent | null>(null);
  useEffect(() => {
    const ev = events[events.length - 1];
    if (ev?.type === "coach_message" && !panels.chat && ev !== lastCounted.current
        && !(ev.data?.meta as { agent?: string } | undefined)?.agent) {
      lastCounted.current = ev;
      setUnread((u) => u + 1);
    }
  }, [events, panels.chat]);
  useEffect(() => { if (panels.chat) setUnread(0); }, [panels.chat]);

  function togglePanel(key: keyof Panels) {
    // expanding an assistance panel costs a confirmation — collapsing is free,
    // and progress/notes aren't aids at all so they toggle unconditionally
    if (!panels[key] && (key === "sheet" || key === "chat")) {
      setLazyAsk(key);
      return;
    }
    setPanels((p) => {
      const next = { ...p, [key]: !p[key] };
      savePanels(next);
      return next;
    });
  }

  function setPanelWidth(key: keyof PanelWidths, px: number) {
    setWidths((w) => {
      const next = { ...w, [key]: clampWidth(px) };
      localStorage.setItem(WIDTHS_KEY, JSON.stringify(next));
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

  const [netBusy, setNetBusy] = useState(false);
  const [netMsg, setNetMsg] = useState<string | null>(null);
  async function toggleInternet() {
    const want = !session?.kali_internet;
    setNetBusy(true);
    setNetMsg(null);
    try {
      const r = await api.post<{ enabled: boolean; ip?: string }>(
        `/api/sessions/${sessionId}/internet`, { enabled: want });
      setNetMsg(r.enabled && r.ip ? `LAN ${r.ip}` : null);
      qc.invalidateQueries({ queryKey: ["session", sessionId] });
      if (r.enabled && r.ip) setTimeout(() => setNetMsg(null), 8000);
    } catch (e) {
      setNetMsg(e instanceof Error ? e.message.slice(0, 80) : "toggle failed");
    } finally {
      setNetBusy(false);
    }
  }

  const state = session?.state;
  const consoleReady = state === "ready" || state === "active";

  // ---------- terminal tabs ----------
  const tabs = termPrefs.tabs;
  const dockedTabs = tabs.filter((t) => t.docked);
  const mainTabs = tabs.filter((t) => !t.docked);
  const dockChan = activeDock && dockedTabs.some((t) => t.chan === activeDock)
    ? activeDock : dockedTabs[0]?.chan ?? null;

  function updateTerms(mut: (p: TermPrefs) => void) {
    // deep-copy tabs: StrictMode double-invokes updaters — mutating shared
    // objects would flip flags twice. Copies keep each invocation idempotent.
    setTermPrefs((prev) => {
      const next = { ...prev, tabs: prev.tabs.map((t) => ({ ...t })) };
      mut(next);
      saveTerms(sessionId, next);
      return next;
    });
  }

  function newChanId(): string {
    // crypto.randomUUID is secure-context-only — over plain http://LAN it
    // doesn't exist and the + button dies silently. getRandomValues works
    // everywhere; chan ids are UI handles (server only checks the format).
    const b = new Uint8Array(8);
    if (crypto.getRandomValues) crypto.getRandomValues(b);
    else for (let i = 0; i < b.length; i++) b[i] = Math.random() * 256;
    return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  }

  function addTerm() {
    const chan = newChanId();
    updateTerms((p) => {
      p.tabs.push({ chan, title: `Term ${p.tabs.length + 1}`, docked: false });
      p.active = chan;
    });
  }

  function closeTerm(chan: string) {
    updateTerms((p) => {
      p.tabs = p.tabs.filter((t) => t.chan !== chan);
      if (p.active === chan) p.active = "desktop";
    });
    if (activeDock === chan) setActiveDock(null);
    setTermStates((s) => { const n = { ...s }; delete n[chan]; return n; });
  }

  function toggleDock(chan: string) {
    const docking = !tabs.find((t) => t.chan === chan)?.docked;
    updateTerms((p) => {
      const t = p.tabs.find((t) => t.chan === chan);
      if (!t) return;
      t.docked = docking;
      if (docking && p.active === chan) p.active = "desktop";
      if (!docking) p.active = chan;
    });
    if (docking) setActiveDock(chan);
  }

  function setAutonomy(level: number) {
    api.post(`/api/sessions/${sessionId}/autonomy`, { level })
      .then(() => qc.invalidateQueries({ queryKey: ["session", sessionId] }))
      .catch(() => {});
  }

  function setSubagents(enabled: boolean) {
    api.post(`/api/sessions/${sessionId}/subagents`, { enabled })
      .then(() => qc.invalidateQueries({ queryKey: ["session", sessionId] }))
      .catch(() => {});
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="min-w-0 truncate font-semibold">{session?.quest_id ?? `session ${sessionId}`}</h1>
          {state && (
            <Badge variant={
              state === "active" ? "success"
              : state === "failed" || state === "aborted" ? "danger"
              : state === "solved" ? "accent" : "warning"}>
              {state}
            </Badge>
          )}
          {session?.error && <span className="max-w-48 truncate text-xs text-danger">{session.error}</span>}
          {netMsg && <span className="max-w-56 truncate text-xs text-muted">{netMsg}</span>}
          {(state === "deploying" || state === "queued") && session?.created_at && (
            <DeployElapsed since={session.created_at} />
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {state === "ready" && (
            <Button size="sm" variant="success" onClick={activate} title="Start hacking">
              <Play className="h-3.5 w-3.5" /> <span className="hidden lg:inline">Start hacking</span>
            </Button>
          )}
          {consoleReady && (
            <>
              <Button variant="secondary" size="sm" onClick={() => reset(false)}
                title="Roll back all range VMs to the post-deploy snapshot">
                <RotateCcw className="h-3.5 w-3.5" /> <span className="hidden lg:inline">Soft reset</span>
              </Button>
              <Button variant="secondary" size="sm" onClick={() => reset(true)}
                title="Destroy the range and redeploy from scratch">
                <RotateCw className="h-3.5 w-3.5" /> <span className="hidden lg:inline">Hard reset</span>
              </Button>
            </>
          )}
          {state && state !== "aborted" && state !== "failed" && (
            <div className="border-l border-border pl-2">
              <Button variant="danger" size="sm" onClick={abort}
                title={state === "solved" ? "Tear down the range" : "End session and destroy the range"}>
                <Square className="h-3.5 w-3.5" />
                <span className="hidden lg:inline">{state === "solved" ? "Tear down" : "End session"}</span>
              </Button>
            </div>
          )}
          {session?.autonomy_level !== undefined && (
            <AutonomyToggle autonomy={session.autonomy_level}
              onAutonomy={setAutonomy} />
          )}
          {session?.subagents_enabled !== undefined && (
            <SubagentsToggle enabled={session.subagents_enabled}
              onToggle={setSubagents} />
          )}
          <div className="ml-1 flex items-center gap-0.5 border-l border-border pl-2">
            <IconButton icon={CheckSquare} label="Progress"
              active={panels.progress} onClick={() => togglePanel("progress")} />
            <IconButton icon={BookOpen} label="Reference sheet"
              active={panels.sheet} onClick={() => togglePanel("sheet")} />
            <IconButton icon={NotebookPen} label="Notes"
              active={panels.notes} onClick={() => togglePanel("notes")} />
            <IconButton icon={Bot} label="Coach panel"
              active={panels.chat} badgeDot={unread > 0} onClick={() => togglePanel("chat")} />
            {consoleReady && (
              <IconButton icon={Wifi} label={netBusy ? "Kali internet: switching…"
                : `Kali internet: ${session?.kali_internet ? "ON" : "OFF"} — click to ${session?.kali_internet ? "disconnect" : "connect"} (net1 → LAN)`}
                active={!!session?.kali_internet} disabled={netBusy}
                onClick={toggleInternet} />
            )}
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {panels.progress ? (
          <>
            <div className="flex shrink-0 flex-col border-r border-border bg-surface"
              style={{ width: widths.progress }}>
              <Tabs className="m-2" tabs={[
                { id: "objectives", label: <span className="flex items-center gap-1"><CheckSquare className="h-3.5 w-3.5" /> Objectives</span> },
                { id: "log", label: <span className="flex items-center gap-1"><FileText className="h-3.5 w-3.5" /> Log</span> },
              ]} active={progressTab} onChange={setProgressTab} />
              <div className="min-h-0 flex-1">
                {progressTab === "objectives" && <ObjectivesPanel sessionId={sessionId} events={events} />}
                {progressTab === "log" && <DeployLog lines={logLines} state={state} fill />}
              </div>
            </div>
            <ResizeHandle side="left" getWidth={() => widths.progress}
              onResize={(px) => setPanelWidth("progress", px)}
              onReset={() => setPanelWidth("progress", WIDTH_DEFAULTS.progress)} />
          </>
        ) : (
          <CollapsedStrip edge="left" icon={CheckSquare} label="Progress"
            onClick={() => togglePanel("progress")} />
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          {consoleReady && (
            <div className="flex h-8 shrink-0 items-center gap-0.5 overflow-x-auto border-b border-border bg-surface px-1.5">
              <button
                onClick={() => updateTerms((p) => { p.active = "desktop"; })}
                className={cn(
                  "flex h-6 items-center gap-1.5 rounded px-2.5 text-xs transition",
                  termPrefs.active === "desktop"
                    ? "bg-surface-2 text-foreground" : "text-muted hover:text-foreground")}>
                <Monitor className="h-3.5 w-3.5" /> Desktop
              </button>
              {mainTabs.map((t) => (
                <span key={t.chan}
                  className={cn(
                    "group flex h-6 items-center gap-1 rounded pl-2 pr-0.5 text-xs transition",
                    termPrefs.active === t.chan
                      ? "bg-surface-2 text-foreground" : "text-muted hover:text-foreground")}>
                  <button className="flex items-center gap-1.5"
                    onClick={() => updateTerms((p) => { p.active = t.chan; })}>
                    <TerminalSquare className="h-3.5 w-3.5" />
                    <span className={TERM_DOT[termStates[t.chan] ?? "connecting"]}>●</span>
                    {t.title}
                  </button>
                  <button title="Move to dock"
                    onClick={() => toggleDock(t.chan)}
                    className="rounded p-0.5 text-muted opacity-0 transition hover:text-foreground group-hover:opacity-100">
                    <PanelBottom className="h-3 w-3" />
                  </button>
                  <button title="Close terminal"
                    onClick={() => closeTerm(t.chan)}
                    className="rounded p-0.5 text-muted opacity-0 transition hover:text-danger group-hover:opacity-100">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
              <button title="New terminal tab" onClick={addTerm}
                className="ml-0.5 flex h-5 w-5 items-center justify-center rounded
                  text-muted transition hover:bg-surface-2 hover:text-foreground">
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
          )}

          <div className="relative min-h-0 flex-1">
            {consoleReady && <LiveStatsOverlay sessionId={sessionId} />}
            {consoleReady ? (
              <>
                {/* remount on ready_at → after a reset the stale VNC session reconnects;
                    hidden (not unmounted) on tab switch so RFB + shells stay attached */}
                <div className={cn("absolute inset-0",
                  termPrefs.active !== "desktop" && "hidden")}>
                  <ConsoleView key={`${sessionId}-${session?.ready_at ?? ""}`}
                    sessionId={sessionId} />
                </div>
                {mainTabs.map((t) => (
                  <div key={t.chan} className={cn("absolute inset-0",
                    termPrefs.active !== t.chan && "hidden")}>
                    {/* ready_at in key: after a reset (fresh VM) the terminal
                        remounts like the console — ws retries alone die
                        during the deploy gap */}
                    <TerminalView key={`${t.chan}-${session?.ready_at ?? ""}`}
                      sessionId={sessionId} chan={t.chan}
                      visible={termPrefs.active === t.chan}
                      onStatus={(s) => setTermStates((p) =>
                        p[t.chan] === s ? p : { ...p, [t.chan]: s })} />
                  </div>
                ))}
              </>
            ) : isLoading ? (
              <div className="grid h-full place-items-center text-sm text-muted">Loading…</div>
            ) : state === "deploying" || state === "queued" || state === "resetting" || state === "aborting" ? (
              <DeployLog lines={logLines} state={state} />
            ) : (
              <div className="grid h-full place-items-center text-sm text-muted">
                <div className="text-center">
                  <div>Session is {state ?? "unknown"}.</div>
                  {state === "solved" && (
                    <div className="mt-3">
                      <div className="text-base font-semibold text-accent">Quest solved</div>
                      {attempt ? (
                        <div className="mt-1 text-xs">
                          {attempt.score} pts · {fmtDuration(attempt.duration_s)}
                          {attempt.breakdown?.flags != null && (
                            <div className="mt-1 text-muted">
                              flags {attempt.breakdown.flags}
                              {attempt.breakdown.time_bonus
                                ? `  +  time ${attempt.breakdown.time_bonus}` : ""}
                              {attempt.breakdown.hint_cost
                                ? `  −  hints ${attempt.breakdown.hint_cost}` : ""}
                              {attempt.breakdown.takeover_penalty
                                ? `  −  takeover ${attempt.breakdown.takeover_penalty}` : ""}
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="mt-1 text-xs">check the leaderboard for your score</div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {dockChan && (
            <div className="flex shrink-0 flex-col border-t border-border"
              style={{ height: termPrefs.dockH }}>
              <ResizeHandle side="top" getWidth={() => termPrefs.dockH}
                onResize={(px) => updateTerms((p) => {
                  p.dockH = Math.min(DOCK_H_MAX, Math.max(DOCK_H_MIN, Math.round(px)));
                })}
                onReset={() => updateTerms((p) => { p.dockH = DOCK_H_DEFAULT; })} />
              <div className="flex h-7 shrink-0 items-center gap-0.5 border-b border-border bg-surface px-1.5">
                {dockedTabs.map((t) => (
                  <span key={t.chan}
                    className={cn(
                      "group flex h-5 items-center gap-1 rounded pl-2 pr-0.5 text-xs transition",
                      dockChan === t.chan
                        ? "bg-surface-2 text-foreground" : "text-muted hover:text-foreground")}>
                    <button className="flex items-center gap-1.5"
                      onClick={() => setActiveDock(t.chan)}>
                      <TerminalSquare className="h-3 w-3" />
                      <span className={TERM_DOT[termStates[t.chan] ?? "connecting"]}>●</span>
                      {t.title}
                    </button>
                    <button title="Undock"
                      onClick={() => toggleDock(t.chan)}
                      className="rounded p-0.5 text-muted opacity-0 transition hover:text-foreground group-hover:opacity-100">
                      <PanelTop className="h-3 w-3" />
                    </button>
                    <button title="Close terminal"
                      onClick={() => closeTerm(t.chan)}
                      className="rounded p-0.5 text-muted opacity-0 transition hover:text-danger group-hover:opacity-100">
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
              <div className="min-h-0 flex-1">
                {dockedTabs.map((t) => (
                  <div key={t.chan} className={cn("h-full", dockChan !== t.chan && "hidden")}>
                    <TerminalView key={`${t.chan}-${session?.ready_at ?? ""}`}
                      sessionId={sessionId} chan={t.chan}
                      visible={dockChan === t.chan}
                      onStatus={(s) => setTermStates((p) =>
                        p[t.chan] === s ? p : { ...p, [t.chan]: s })} />
                  </div>
                ))}
              </div>
            </div>
          )}

          <NotesPanel sessionId={sessionId} open={panels.notes}
            onToggle={() => togglePanel("notes")} />
        </div>

        {panels.sheet ? (
          <>
            <ResizeHandle side="right" getWidth={() => widths.sheet}
              onResize={(px) => setPanelWidth("sheet", px)}
              onReset={() => setPanelWidth("sheet", WIDTH_DEFAULTS.sheet)} />
            <div className="shrink-0 border-l border-border" style={{ width: widths.sheet }}>
              <SheetPanel sessionId={sessionId} events={events} />
            </div>
          </>
        ) : (
          <CollapsedStrip icon={BookOpen} label="Reference"
            onClick={() => togglePanel("sheet")} />
        )}

        {panels.chat ? (
          <>
            <ResizeHandle side="right" getWidth={() => widths.chat}
              onResize={(px) => setPanelWidth("chat", px)}
              onReset={() => setPanelWidth("chat", WIDTH_DEFAULTS.chat)} />
            <div className="flex shrink-0 flex-col border-l border-border bg-surface"
              style={{ width: widths.chat }}>
              <ChatPanel sessionId={sessionId} events={events}
                autonomy={session?.autonomy_level}
                onAutonomy={setAutonomy}
                subagents={session?.subagents_enabled}
                onSubagents={setSubagents} />
            </div>
          </>
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

/** Elapsed-time badge while a range deploys — big labs can take 30+ min, so
 *  make the wait visible instead of looking frozen. */
function DeployElapsed({ since }: { since: string }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30000);
    return () => clearInterval(t);
  }, []);
  // backend timestamps are UTC without a suffix — make that explicit for Date
  const started = new Date(since.endsWith("Z") || since.includes("+") ? since : since + "Z");
  const mins = Math.max(0, Math.round((Date.now() - started.getTime()) / 60000));
  return <Badge variant="warning">deploying {mins}min</Badge>;
}

function CollapsedStrip({ icon: Icon, label, unread, edge = "right", onClick }: {
  icon: React.ElementType; label: string; unread?: number;
  edge?: "left" | "right"; onClick: () => void;
}) {
  return (
    <button onClick={onClick} title={`Show ${label}`}
      className={cn("flex w-11 shrink-0 flex-col items-center gap-3 bg-surface py-3 text-muted hover:text-foreground cursor-pointer",
        edge === "left" ? "border-r border-border" : "border-l border-border")}>
      <span className="relative">
        <Icon className="h-4 w-4" />
        {!!unread && <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-accent" />}
      </span>
      <span className="text-[10px] tracking-wide [writing-mode:vertical-rl]">{label}</span>
    </button>
  );
}
