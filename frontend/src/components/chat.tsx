import { memo, useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Bot, CheckCircle2, ChevronRight, Circle, Lightbulb, ListTodo, Loader2, Pause, Play, Radio, Terminal, User, X } from "lucide-react";
import { api, type ChatMessage, type WsEvent } from "@/lib/api";
import { Button } from "@/components/ui";
import { MarkdownView } from "@/components/markdown";
import { cn } from "@/lib/utils";

type Resolved = "confirmed" | "rejected" | "error" | string;

interface Draft { text: string; reasoning: string; kind: string; done: boolean;
                  updated: number }

/** Roster entry pushed via coach_agents — drives a worker's chip. */
interface AgentInfo {
  id: string; task: string; status: string; actions: number; elapsed: number;
}
interface AgentActivity { text: string; output?: string; since: number }
/** Everything the UI knows about one subagent — roster info, its live
 * indicator, its streaming drafts, plus a per-chip unread counter. */
interface AgentFeed {
  info?: AgentInfo;
  drafts: Record<string, Draft>;
  activity: AgentActivity | null;
  unseen: number;
}

/** Merge defaults → previous → patch into one agent's feed record. */
function patchFeed(all: Record<string, AgentFeed>, id: string,
                   patch: Partial<AgentFeed>): Record<string, AgentFeed> {
  const prev = all[id];
  return { ...all, [id]: {
    info: patch.info ?? prev?.info,
    drafts: patch.drafts ?? prev?.drafts ?? {},
    activity: patch.activity !== undefined ? patch.activity
                                           : (prev?.activity ?? null),
    unseen: patch.unseen ?? prev?.unseen ?? 0,
  } };
}

const AGENT_TERMINAL = new Set(["done", "timeout", "failed", "killed"]);

/** Open drafts older than this with no live activity are ghosts — their
 * turn died (cancel/restart/dropped 'done'); drop the bubble. */
const DRAFT_STALE_MS = 90_000;

function pruneStaleOpenDrafts(ds: Record<string, Draft>, now: number) {
  const stale = Object.keys(ds).filter(
    (k) => !ds[k].done && now - ds[k].updated > DRAFT_STALE_MS);
  if (!stale.length) return null;
  const n = { ...ds };
  for (const k of stale) delete n[k];
  return n;
}

const AGENT_STATUS_DOT: Record<string, string> = {
  running: "bg-primary animate-pulse",
  done: "bg-success",
  timeout: "bg-warning",
  failed: "bg-danger",
  killed: "bg-muted",
};

/** terminal-status → outcome color for the feed's final-result card */
const AGENT_STATUS_EDGE: Record<string, string> = {
  done: "border-l-success",
  timeout: "border-l-warning",
  failed: "border-l-danger",
  killed: "border-l-muted",
};

/** Model chain-of-thought — muted block above the answer. Open while the
 * draft streams, a collapsed <details> once the real message lands. */
function ThinkingBlock({ text, open }: { text: string; open?: boolean }) {
  if (!text.trim()) return null;
  if (open) {
    return (
      <div className="mb-2 border-l-2 border-accent/40 pl-2">
        <div className="mb-0.5 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-accent/80">
          <Bot className="h-3 w-3" /> thinking
        </div>
        <div className="whitespace-pre-wrap text-xs leading-snug text-muted">{text}</div>
      </div>
    );
  }
  return (
    <details className="mb-2">
      <summary className="cursor-pointer select-none text-[10px] font-semibold uppercase tracking-wide text-accent/70 hover:text-accent">
        thinking
      </summary>
      <div className="mt-1 whitespace-pre-wrap border-l-2 border-accent/30 pl-2 text-xs leading-snug text-muted">
        {text}
      </div>
    </details>
  );
}

const AUTONOMY = [
  { level: 1, short: "Obs", name: "Observer", tip: "watches and hints only" },
  { level: 2, short: "Ment", name: "Mentor", tip: "adaptive guidance" },
  { level: 3, short: "Co", name: "Copilot", tip: "suggests commands — you confirm" },
  { level: 4, short: "Auto", name: "Autonomous", tip: "executes on Kali itself" },
];

export function AutonomyToggle({ autonomy, onAutonomy }: {
  autonomy: number;
  onAutonomy: (level: number) => void;
}) {
  return (
    <span className="flex items-center gap-0.5 rounded-md border border-border p-0.5"
      title="Coach autonomy — same as /autonomy <level> in chat">
      {AUTONOMY.map((a) => (
        <button
          key={a.level}
          title={`${a.level} — ${a.name}: ${a.tip}`}
          onClick={() => {
            if (a.level === autonomy) return;
            if (a.level === 4 &&
              !confirm("Autonomous mode lets the coach execute commands on Kali. Enable?")) return;
            onAutonomy(a.level);
          }}
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-medium leading-none transition-colors cursor-pointer",
            a.level === autonomy
              ? "bg-primary/20 text-primary"
              : "text-muted hover:bg-surface-2 hover:text-foreground",
          )}>
          {a.level}·{a.short}
        </button>
      ))}
    </span>
  );
}

export function SubagentsToggle({ enabled, onToggle }: {
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  return (
    <button
      title={enabled
        ? "Subagents on — the coach can spawn parallel workers on tmux panes w1, w2, … (same as /subagents on)"
        : "Subagents off — enable parallel worker agents (same as /subagents on)"}
      onClick={() => onToggle(!enabled)}
      className={cn(
        "rounded-md border border-border px-1.5 py-0.5 text-[10px] font-medium leading-none transition-colors cursor-pointer",
        enabled
          ? "bg-primary/20 text-primary"
          : "text-muted hover:bg-surface-2 hover:text-foreground",
      )}>
      {enabled ? "Sub·on" : "Sub"}
    </button>
  );
}

export function CoachToggle({ enabled, onToggle }: {
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  return (
    <Button size="icon" variant="ghost"
      title={enabled
        ? "Pause Elliot — he stops acting and thinking entirely; the range stays up, resume anytime"
        : "Resume Elliot — picks up where he paused"}
      aria-label={enabled ? "Pause Elliot" : "Resume Elliot"}
      onClick={() => onToggle(!enabled)}
      className={cn(!enabled && "text-warning")}>
      {enabled ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
    </Button>
  );
}

export function ChatPanel({ sessionId, events, autonomy, onAutonomy,
                            subagents, onSubagents,
                            coachEnabled, onCoachToggle }: {
  sessionId: number; events: WsEvent[];
  autonomy?: number;
  onAutonomy?: (level: number) => void;
  subagents?: boolean;
  onSubagents?: (enabled: boolean) => void;
  coachEnabled?: boolean;
  onCoachToggle?: (enabled: boolean) => void;
}) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [thinking, setThinking] = useState(false);
  const [sendError, setSendError] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [activity, setActivity] = useState<AgentActivity | null>(null);
  // parallel subagent feeds — w1..wN keyed by agent id; "main" is the coach
  const [agents, setAgents] = useState<Record<string, AgentFeed>>({});
  const [selAgent, setSelAgent] = useState("main");
  const [now, setNow] = useState(0);
  const [atBottom, setAtBottom] = useState(true);
  const [unseen, setUnseen] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const thinkTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const actOutRef = useRef<HTMLPreElement>(null);
  const draftTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const lastEv = useRef<WsEvent | null>(null);

  const removeDraft = useCallback((id: string) => {
    clearTimeout(draftTimers.current.get(id));
    draftTimers.current.delete(id);
    setDrafts((d) => { const n = { ...d }; delete n[id]; return n; });
  }, []);

  const [mainUnseen, setMainUnseen] = useState(0);

  const removeAgentDraft = useCallback((agent: string, id: string) => {
    clearTimeout(draftTimers.current.get(id));
    draftTimers.current.delete(id);
    setAgents((a) => {
      const f = a[agent];
      if (!f || !(id in f.drafts)) return a;
      const drafts = { ...f.drafts };
      delete drafts[id];
      return { ...a, [agent]: { ...f, drafts } };
    });
  }, []);

  const selectAgent = useCallback((id: string) => {
    setSelAgent(id);
    setAtBottom(true);
    setUnseen(0);
    if (id !== "main") {
      setAgents((a) => a[id] ? { ...a, [id]: { ...a[id], unseen: 0 } } : a);
    } else {
      setMainUnseen(0);
    }
  }, []);

  useEffect(() => () => {
    clearTimeout(thinkTimer.current);
    draftTimers.current.forEach(clearTimeout);
  }, []);

  // session switch — don't leak the other session's feeds/drafts/chips
  useEffect(() => {
    setAgents({});
    setSelAgent("main");
    setDrafts({});
    setActivity(null);
    setMainUnseen(0);
    lastEv.current = null;
  }, [sessionId]);

  const { data: messages } = useQuery({
    queryKey: ["chat", sessionId],
    queryFn: () => api.get<ChatMessage[]>(`/api/sessions/${sessionId}/chat`),
  });

  // worker chips must also appear from history alone — the sticky roster
  // push expires after 120s while persisted worker messages live on, so a
  // late reload derives the agents from the messages' own agent tags
  useEffect(() => {
    if (!messages) return;
    const ids = new Set<string>();
    for (const m of messages) {
      const a = m.meta?.agent;
      if (typeof a === "string" && a && a !== "main") ids.add(a);
    }
    if (!ids.size) return;
    setAgents((a) => {
      let changed = false;
      const next = { ...a };
      for (const id of ids) {
        if (!next[id]) {
          next[id] = { drafts: {}, activity: null, unseen: 0 };
          changed = true;
        }
      }
      return changed ? next : a;
    });
  }, [messages]);

  // live events: coach messages arrive over the session WS. Process EVERY
  // fresh event — replay sends several per frame and React batches renders,
  // so last-element-only would silently drop roster/activity frames.
  useEffect(() => {
    let idx = lastEv.current ? events.lastIndexOf(lastEv.current) + 1 : 0;
    if (idx < 0) idx = 0;           // trimmed out of the capped window
    const fresh = events.slice(idx);
    if (!fresh.length) return;
    lastEv.current = events[events.length - 1];
    for (const ev of fresh) {
      if (!ev.data) continue;
      const agent = (ev.data.agent as string | undefined) ?? "main";
      if (ev.type === "coach_message") {
        const msg = ev.data as ChatMessage;
        qc.setQueryData<ChatMessage[]>(["chat", sessionId], (old) => {
          if (old?.some((m) => m.id === msg.id)) return old;
          return [...(old ?? []), { ...msg, ts: msg.ts ?? new Date().toISOString() }];
        });
        const ma = msg.meta?.agent as string | undefined;
        // a worker's report must not clear the spinner for the parent's
        // in-flight reply — only main-feed coach messages count
        if (msg.role === "coach" && (!ma || ma === "main")) setThinking(false);
        // worker messages bump that chip's unread dot, not the panel's;
        // main messages bump the coach chip while a feed is open
        if ((!ma || ma === "main") && selAgent !== "main" && msg.role === "coach") {
          setMainUnseen((n) => n + 1);
        }
        if (ma && ma !== "main") {
          setAgents((a) => patchFeed(a, ma, {
            unseen: selAgent === ma ? 0 : (a[ma]?.unseen ?? 0) + 1 }));
        }
        // the persisted message replaces its streaming draft atomically
        const did = msg.meta?.draft_id;
        if (typeof did === "string") removeDraft(did);
      }
      // streaming drafts: cumulative content relayed while the LLM generates
      if (ev.type === "coach_stream" && ev.data.draft_id) {
        const { draft_id, content = "", reasoning = "", kind = "chat", done } = ev.data as {
          draft_id: string; content?: string; reasoning?: string;
          kind?: string; done?: boolean;
        };
        // ev.ts = backend publish time — a replayed stale draft is already
        // old, so the GC drops it quickly instead of re-ghosting for 90s
        const updated = typeof ev.ts === "number" ? ev.ts * 1000 : Date.now();
        const d: Draft = { text: content, reasoning, kind, done: !!done,
                           updated };
        if (agent === "main") {
          setDrafts((ds) => ({ ...ds, [draft_id]: d }));
        } else {
          setAgents((a) => patchFeed(a, agent, {
            drafts: { ...(a[agent]?.drafts ?? {}), [draft_id]: d },
            unseen: selAgent === agent ? (a[agent]?.unseen ?? 0)
                                       : (a[agent]?.unseen ?? 0) + 1 }));
        }
        if (done) {
          // the real message may arrive a beat later — grace period, then drop
          clearTimeout(draftTimers.current.get(draft_id));
          draftTimers.current.set(draft_id, setTimeout(
            () => agent === "main" ? removeDraft(draft_id)
                                   : removeAgentDraft(agent, draft_id), 2500));
        }
      }
      // 'coach working' status — emitted while slow actions (exec, screen
      // analysis, flag checks) are in flight; per-agent so workers update
      // their own chip, never the parent's
      if (ev.type === "coach_activity") {
        const { active, text, output } = ev.data as
          { active: boolean; text?: string; output?: string };
        // events are mergeable — an output-only tick keeps the label, a
        // label-only tick keeps the accumulated output
        const merge = (prev: AgentActivity | null): AgentActivity | null =>
          active
            ? { text: text || prev?.text || "working…",
                output: output ?? prev?.output,
                since: prev?.since ?? Date.now() }
            : null;
        if (agent === "main") {
          setActivity(merge);
        } else {
          setAgents((a) => patchFeed(a, agent, {
            activity: merge(a[agent]?.activity ?? null) }));
        }
      }
      // worker roster snapshot — chip labels/status; feed data is preserved
      if (ev.type === "coach_agents") {
        const list = (ev.data.agents ?? []) as AgentInfo[];
        setAgents((a) => {
          let next = a;
          for (const info of list) {
            next = patchFeed(next, info.id, { info });
          }
          return next;
        });
      }
      // suggestion confirm/reject → mark the matching suggestion message resolved
      if (ev.type === "coach_action" && ev.data.status && ev.data.id) {
        const { id, status } = ev.data as { id: number; status: string };
        if (status === "confirmed" || status === "rejected" || status === "error") {
          markResolved(id, status);
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events, sessionId, qc, removeDraft, removeAgentDraft, selAgent]);

  // tick the elapsed counter once a second while any agent is working;
  // 5min staleness cap covers a coach dying mid-action. The same tick runs
  // the ghost-draft GC — an open draft needs deltas every DRAFT_STALE_MS or
  // a live activity line, otherwise its turn died silently upstream
  const selFeed = selAgent !== "main" ? agents[selAgent] : undefined;
  const anyAgentLive = Object.values(agents).some(
    (a) => a.activity || a.info?.status === "running");
  const anyDrafts = Object.keys(drafts).length > 0
    || Object.values(agents).some((f) => Object.keys(f.drafts).length > 0);
  useEffect(() => {
    if (!activity && !anyAgentLive && !anyDrafts) return;
    actOutRef.current?.scrollTo({ top: actOutRef.current.scrollHeight });
    setNow(Date.now());
    const iv = setInterval(() => {
      const n = Date.now();
      setNow(n);
      setActivity((prev) => (prev && n - prev.since > 300_000 ? null : prev));
      // ghost-draft GC: a live exec pauses deltas legitimately (activity is
      // set then) — only prune when nothing at all is happening
      if (!activity) {
        setDrafts((ds) => pruneStaleOpenDrafts(ds, n) ?? ds);
      }
      setAgents((a) => {
        let next: Record<string, AgentFeed> | null = null;
        for (const [id, f] of Object.entries(a)) {
          const pruned = f.activity ? null
                                    : pruneStaleOpenDrafts(f.drafts, n);
          if (pruned) {
            next ??= { ...a };
            next[id] = { ...f, drafts: pruned };
          }
        }
        return next ?? a;
      });
    }, 1000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activity, anyAgentLive, anyDrafts]);

  // smart autoscroll: follow the tail only while the user is already at the bottom
  const agentDrafts = selFeed?.drafts ?? {};
  const draftSize = Object.values(drafts).reduce((a, d) => a + d.text.length, 0)
    + Object.values(agentDrafts).reduce((a, d) => a + d.text.length, 0);
  const visible = (messages ?? []).filter((m) =>
    selAgent === "main"
      ? !m.meta?.agent || m.meta.agent === "main"
      : m.meta?.agent === selAgent);
  // persistent plan strip — the selected feed's latest update_plan rides
  // above the composer while any item is still open (gone = all done or
  // none set); history and live WS events both carry meta.plan
  let planItems: PlanItem[] | null = null;
  for (let i = visible.length - 1; i >= 0; i--) {
    const p = visible[i].meta?.plan;
    if (Array.isArray(p) && p.length) { planItems = p as PlanItem[]; break; }
  }
  useEffect(() => {
    if (atBottom) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    else setUnseen((n) => n + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible.length, draftSize, selAgent]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setAtBottom(near);
    if (near) setUnseen(0);
  }

  function scrollToBottom() {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    setUnseen(0);
  }

  async function send() {
    const content = text.trim();
    if (!content) return;
    // the composer always addresses the main coach — jump to its feed so
    // the sent message (and the reply) is visible where the user expects it
    if (selAgent !== "main") selectAgent("main");
    setText("");
    if (composerRef.current) composerRef.current.style.height = "auto";
    setThinking(true);
    clearTimeout(thinkTimer.current);
    // the LLM turn can take a while — don't show "thinking" forever
    thinkTimer.current = setTimeout(() => setThinking(false), 45_000);
    try {
      const r = await api.post<{ id: number }>(`/api/sessions/${sessionId}/chat`, { content });
      setSendError(false);
      // the WS may already have delivered this message — dedupe by id
      qc.setQueryData<ChatMessage[]>(["chat", sessionId], (old) => {
        if (old?.some((m) => m.id === r.id)) return old;
        return [...(old ?? []),
          { id: r.id, role: "user" as const, kind: "chat", content, ts: new Date().toISOString() }];
      });
    } catch {
      setThinking(false);
      setSendError(true);
      setText(content); // don't lose the message on send failure
      setTimeout(() => setSendError(false), 5000);
    }
  }

  /** Patch the suggestion message's resolved state — WS event and this are idempotent. */
  const markResolved = useCallback((actionId: number, status: string) => {
    qc.setQueryData<ChatMessage[]>(["chat", sessionId], (old) =>
      (old ?? []).map((m) =>
        m.kind === "suggestion" && m.meta?.action_id === actionId
          ? { ...m, meta: { ...m.meta, resolved: status } }
          : m));
  }, [qc, sessionId]);

  const confirmAction = useCallback(async (actionId: number, accept: boolean) => {
    try {
      const r = await api.post<{ status: string }>(
        `/api/sessions/${sessionId}/actions/${actionId}/confirm`, { accept });
      markResolved(actionId, r.status ?? (accept ? "confirmed" : "rejected"));
    } catch { /* stays pending — user can retry */ }
  }, [sessionId, markResolved]);

  return (
    <div className="relative flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-3 py-2 text-sm font-medium">
        <span>Elliot <span className="ml-1 text-xs font-normal text-muted">samsepi0l · adaptive hints</span>
          {coachEnabled === false && (
            <span className="ml-1.5 rounded border border-warning/40 bg-warning/10 px-1 py-0.5 text-[10px] font-normal text-warning">paused</span>
          )}
        </span>
        <span className="flex items-center gap-2">
          {autonomy !== undefined && onAutonomy && (
            <AutonomyToggle autonomy={autonomy} onAutonomy={onAutonomy} />
          )}
          {subagents !== undefined && onSubagents && (
            <SubagentsToggle enabled={subagents} onToggle={onSubagents} />
          )}
          {thinking && (
            <span className="flex items-center gap-1 text-xs text-muted">
              <Radio className="h-3 w-3 animate-pulse text-primary" /> thinking…
            </span>
          )}
        </span>
      </div>
      <div ref={scrollRef} onScroll={onScroll} className="flex-1 space-y-3 overflow-auto p-3">
        {selAgent === "main" ? (
          <>
            {visible.map((m) => (
              <Message key={m.id} m={m} onConfirm={confirmAction}
                onSelectAgent={selectAgent} />
            ))}
            {Object.entries(drafts).map(([id, d]) => (
              <DraftBubble key={id} d={d} />
            ))}
            {activity && (
              <div className="flex items-center gap-2 px-1 text-xs text-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                <span className="min-w-0 flex-1 truncate font-mono">
                  {activity.text || "working…"}
                </span>
                <span className="shrink-0 tabular-nums">
                  {Math.floor((now - activity.since) / 1000)}s
                </span>
              </div>
            )}
            {activity?.output && (
              <pre ref={actOutRef}
                className="ml-6 max-h-44 overflow-auto whitespace-pre-wrap break-all rounded-md bg-black/50 p-2 font-mono text-[11px] leading-snug text-muted">
                {activity.output}
              </pre>
            )}
            {thinking && (
              <div className="flex gap-2">
                <div className="mt-0.5 flex h-6 w-6 items-center justify-center rounded-full bg-primary/20 text-primary">
                  <Bot className="h-3.5 w-3.5" />
                </div>
                <div className="rounded-lg bg-surface-2 px-3 py-2">
                  <span className="flex gap-1">
                    {[0, 1, 2].map((i) => (
                      <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted"
                        style={{ animationDelay: `${i * 150}ms` }} />
                    ))}
                  </span>
                </div>
              </div>
            )}
            {!visible.length && !thinking && (
              <p className="p-2 text-sm text-muted">
                Elliot will chime in as you work. Ask questions anytime — he renders
                Markdown, code blocks and diagrams.
              </p>
            )}
          </>
        ) : (
          <WorkerFeed agent={selAgent} feed={selFeed} messages={visible}
            onConfirm={confirmAction} onSelectAgent={selectAgent}
            now={now} actOutRef={actOutRef} />
        )}
        <div ref={bottomRef} />
      </div>
      {!atBottom && (
        <button onClick={scrollToBottom}
          className="absolute bottom-16 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-surface px-3 py-1 text-xs shadow-lg hover:bg-surface-2 cursor-pointer">
          <ArrowDown className="h-3 w-3" />
          {unseen > 0 ? `${unseen} new` : "latest"}
        </button>
      )}
      <div className="border-t border-border">
        {Object.keys(agents).length > 0 && (
          <div className="flex items-center gap-1 overflow-x-auto px-2 pt-1.5">
            <AgentChip label="elliot" title="samsepi0l — main agent, you are chatting with this one"
              selected={selAgent === "main"}
              working={!!activity || Object.keys(drafts).length > 0}
              unseen={selAgent === "main" ? 0 : mainUnseen}
              onClick={() => selectAgent("main")} />
            {Object.keys(agents).sort().map((id) => {
              const f = agents[id];
              return (
                <AgentChip key={id} label={id}
                  title={f.info?.task || `worker ${id}`}
                  status={f.info?.status}
                  selected={selAgent === id}
                  working={!!f.activity}
                  unseen={selAgent === id ? 0 : f.unseen}
                  onClick={() => selectAgent(id)} />
              );
            })}
          </div>
        )}
        {planItems && planItems.some((i) => i.s !== "done") && (
          <div className="px-2 pt-2">
            <PlanCard items={planItems} agent={selAgent} />
          </div>
        )}
        {sendError && (
          <div className="px-3 pt-2 text-xs text-danger">
            Failed to send — your message was restored to the editor.
          </div>
        )}
        <div className="flex items-end gap-2 p-2">
          <textarea
            ref={composerRef}
            value={text}
            rows={1}
            onChange={(e) => {
              setText(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); }
            }}
            placeholder="Ask Elliot… (Shift+Enter for newline)"
            maxLength={8000}
            className="max-h-[120px] min-w-0 flex-1 resize-none rounded-md border border-border bg-surface-2 px-3 py-2 text-sm outline-none placeholder:text-muted focus:border-primary/60" />
          {text.length > 7200 && (
            <span className="pb-1.5 text-[10px] text-muted">{text.length}/8000</span>
          )}
          {coachEnabled !== undefined && onCoachToggle && (
            <CoachToggle enabled={coachEnabled} onToggle={onCoachToggle} />
          )}
          <Button size="icon" aria-label="Send message"
            onClick={() => void send()} disabled={!text.trim()}>
            <ArrowUp className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Streaming draft bubble — shared by the main transcript and agent feeds. */
function DraftBubble({ d }: { d: Draft }) {
  return (
    <div className="flex gap-2">
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/20 text-primary">
        <Bot className="h-3.5 w-3.5" />
      </div>
      <div className="max-w-[85%] rounded-lg bg-surface-2 px-3 py-2 text-sm leading-relaxed">
        <ThinkingBlock text={d.reasoning} open={!d.done} />
        {d.text ? <MarkdownView>{d.text}</MarkdownView> : null}
        {!d.done && (
          <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse rounded-[1px] bg-primary align-text-bottom" />
        )}
      </div>
    </div>
  );
}

/** Live 'working on X' line + accumulating pane output — per agent. */
function ActivityBlock({ activity, now, outRef }: {
  activity: AgentActivity; now: number;
  outRef?: React.RefObject<HTMLPreElement | null>;
}) {
  return (
    <>
      <div className="flex items-center gap-2 px-1 text-xs text-muted">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
        <span className="min-w-0 flex-1 truncate font-mono">
          {activity.text || "working…"}
        </span>
        <span className="shrink-0 tabular-nums">
          {Math.floor((now - activity.since) / 1000)}s
        </span>
      </div>
      {activity.output && (
        <pre ref={outRef}
          className="ml-6 max-h-44 overflow-auto whitespace-pre-wrap break-all rounded-md bg-black/50 p-2 font-mono text-[11px] leading-snug text-muted">
          {activity.output}
        </pre>
      )}
    </>
  );
}

/** One subagent's feed: roster header, its persisted messages (exec/type
 * reports with thinking blocks, final report), live drafts + activity. */
function WorkerFeed({ agent, feed, messages, onConfirm, onSelectAgent, now,
                      actOutRef }: {
  agent: string; feed?: AgentFeed; messages: ChatMessage[];
  onConfirm: (actionId: number, accept: boolean) => void;
  onSelectAgent: (id: string) => void;
  now: number; actOutRef: React.RefObject<HTMLPreElement | null>;
}) {
  const info = feed?.info;
  // no roster info (sticky push expired, chip derived from history) →
  // status unknown: show a muted dot and no fake "running" label
  const status = info?.status;
  const feedDrafts = Object.entries(feed?.drafts ?? {});
  return (
    <>
      <div className="rounded-md border border-border bg-surface-2 px-3 py-2">
        <div className="flex items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full",
            status ? (AGENT_STATUS_DOT[status] ?? "bg-muted")
                   : "bg-muted")} />
          <span className="text-xs font-semibold">{agent}</span>
          <span className="text-[10px] uppercase tracking-wide text-muted">
            {status ?? "worker"}
            {info ? ` · ${info.actions} actions` : ""}
            {info && status !== "running"
              ? ` · ${Math.round(info.elapsed)}s` : ""}
          </span>
        </div>
        {info?.task && (
          <div className="mt-1 text-xs leading-snug text-muted">{info.task}</div>
        )}
      </div>
      {messages.map((m) => (
        <Message key={m.id} m={m} onConfirm={onConfirm}
          onSelectAgent={onSelectAgent} />
      ))}
      {feedDrafts.map(([id, d]) => <DraftBubble key={id} d={d} />)}
      {feed?.activity && (
        <ActivityBlock activity={feed.activity} now={now} outRef={actOutRef} />
      )}
      {(() => {
        // terminal workers get an outcome card at the end of their feed —
        // status-colored edge, elapsed/actions summary, and the last
        // action_report collapsed so a finished worker reads as a closed
        // chapter, not a pane that mysteriously went quiet
        const terminal = status && AGENT_TERMINAL.has(status);
        if (!terminal) return null;
        const report = [...messages].reverse().find(
          (m) => m.kind === "action_report");
        return (
          <div className={cn(
            "rounded-md border border-l-4 border-border bg-surface-2 px-3 py-2",
            AGENT_STATUS_EDGE[status ?? ""] ?? "border-l-muted")}>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted">
              {agent} {status}
              {info ? ` · ${info.actions} actions · ${Math.round(info.elapsed)}s` : ""}
            </div>
            {report ? (
              <details className="mt-1 text-xs">
                <summary className="cursor-pointer select-none text-muted hover:text-foreground">
                  final report
                </summary>
                <div className="mt-1 max-h-96 overflow-auto">
                  <MarkdownView>{report.content}</MarkdownView>
                </div>
              </details>
            ) : (
              <div className="mt-1 text-xs text-muted">
                ended without a report
              </div>
            )}
          </div>
        );
      })()}
      {!messages.length && !feedDrafts.length && !feed?.activity && (
        <p className="p-2 text-sm text-muted">No output from {agent} yet.</p>
      )}
    </>
  );
}

/** terminal-status → a scannable outcome glyph on the roster chip */
const AGENT_STATUS_GLYPH: Record<string, { ch: string; cls: string }> = {
  done: { ch: "✓", cls: "text-success" },
  timeout: { ch: "⏱", cls: "text-warning" },
  failed: { ch: "✗", cls: "text-danger" },
  killed: { ch: "⊘", cls: "text-muted" },
};

/** Clickable live tag above the composer — status dot, label, unseen count. */
function AgentChip({ label, title, status, selected, working, unseen, onClick }: {
  label: string; title?: string; status?: string; selected?: boolean;
  working?: boolean; unseen?: number; onClick: () => void;
}) {
  const glyph = status ? AGENT_STATUS_GLYPH[status] : undefined;
  return (
    <button onClick={onClick} title={title}
      className={cn(
        "flex h-5 shrink-0 items-center gap-1 rounded-full border px-2 text-[10px] font-medium transition-colors cursor-pointer",
        selected
          ? "border-primary/50 bg-primary/15 text-primary"
          : "border-border text-muted hover:bg-surface-2 hover:text-foreground",
        // finished workers stay clickable but visually dimmed
        status && AGENT_TERMINAL.has(status) && "opacity-60")}>
      <span className={cn("h-1.5 w-1.5 rounded-full",
        working ? "bg-primary animate-pulse"
                : (AGENT_STATUS_DOT[status ?? ""] ?? "bg-muted"))} />
      {label}
      {glyph && (
        <span className={cn("text-[9px] leading-none", glyph.cls)}>
          {glyph.ch}
        </span>
      )}
      {!!unseen && (
        <span className="flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-accent px-1 text-[9px] leading-none text-surface">
          {unseen}
        </span>
      )}
    </button>
  );
}

const KIND_STYLE: Record<string, { label: string; cls: string; iconCls: string }> = {
  suggestion: { label: "suggested command", cls: "border border-accent/40 bg-accent/10", iconCls: "bg-accent/15 text-accent" },
  action_report: { label: "elliot action", cls: "border border-warning/40 bg-warning/10", iconCls: "bg-warning/15 text-warning" },
  plan_update: { label: "elliot plan", cls: "border border-primary/30 bg-primary/5", iconCls: "bg-primary/15 text-primary" },
  hint: { label: "hint", cls: "border border-accent/40 bg-accent/5", iconCls: "bg-accent/15 text-accent" },
  nudge: { label: "", cls: "bg-surface-2", iconCls: "bg-primary/20 text-primary" },
};

interface PlanItem { t: string; s?: string; }

function PlanCard({ items, agent }: { items: PlanItem[]; agent?: string }) {
  const done = items.filter((i) => i.s === "done").length;
  const pct = items.length ? Math.round((done / items.length) * 100) : 0;
  return (
    <div className="mt-1 overflow-hidden rounded-md border border-border/60 bg-black/25">
      <div className="flex items-center gap-2 border-b border-border/50 px-2.5 py-1.5">
        <ListTodo className="h-3.5 w-3.5 text-primary" />
        <span className="text-[10px] font-semibold uppercase tracking-wider text-primary">plan</span>
        {agent && agent !== "main" && (
          <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-accent">
            {agent}
          </span>
        )}
        <span className="ml-auto text-[10px] font-medium tabular-nums text-muted">
          {done}/{items.length}
        </span>
        <div className="h-1 w-14 overflow-hidden rounded-full bg-surface-2">
          <div className="h-full rounded-full bg-success transition-all duration-300"
            style={{ width: `${pct}%` }} />
        </div>
      </div>
      <ul className="space-y-1 px-2.5 py-2">
        {items.map((i, k) => (
          <li key={k} className="flex items-start gap-2 text-xs leading-snug">
            {i.s === "done"
              ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
              : i.s === "doing"
                ? <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-pulse text-warning" />
                : <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted/60" />}
            <span className={
              i.s === "done" ? "text-muted line-through opacity-60"
                : i.s === "doing" ? "font-medium text-foreground"
                : "text-muted"}>
              {i.t}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// memoized — a new WS event would otherwise re-parse every message's markdown
const Message = memo(function Message({ m, onConfirm, onSelectAgent }: {
  m: ChatMessage; onConfirm: (actionId: number, accept: boolean) => void;
  onSelectAgent?: (id: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const isCoach = m.role === "coach";
  const isSystem = m.role === "system";
  const suggestion = m.kind === "suggestion" ? m.meta : null;
  const actionId = suggestion?.action_id as number | undefined;
  const resolved = (m.meta?.resolved as Resolved | undefined) ?? null;
  const style = KIND_STYLE[m.kind] ?? { label: "", cls: "bg-surface-2", iconCls: "bg-primary/20 text-primary" };

  // system notices render as quiet centered separators, not bubbles
  if (isSystem) {
    return (
      <div className="flex items-center gap-2 px-2 py-0.5">
        <div className="h-px flex-1 bg-border/60" />
        <span className="max-w-[80%] truncate text-[10px] uppercase tracking-wide text-muted">
          {m.content}
        </span>
        <div className="h-px flex-1 bg-border/60" />
      </div>
    );
  }

  return (
    <div className={cn("flex gap-2", m.role === "user" && "flex-row-reverse")}>
      <div className={cn("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
        isCoach ? (style.iconCls || "bg-primary/20 text-primary") : "bg-surface-2 text-muted")}>
        {isCoach
          ? (m.kind === "hint" ? <Lightbulb className="h-3.5 w-3.5" />
            : m.kind === "plan_update"
              ? <ListTodo className="h-3.5 w-3.5" />
            : m.kind === "suggestion" || m.kind === "action_report"
              ? <Terminal className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />)
          : <User className="h-3.5 w-3.5" />}
      </div>
      <div className={cn("max-w-[85%] rounded-lg px-3 py-2 text-sm leading-relaxed",
        m.role === "user" ? "bg-primary/15" : style.cls)}>
        {(() => {
          // a worker's final report must name its author — "w2 report",
          // not the generic "elliot action" label (main stays as-is)
          const agent = m.meta?.agent as string | undefined;
          const label = (m.kind === "action_report" && agent && agent !== "main")
            ? `${agent} report` : style.label;
          return label && (
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
              {label}
              {m.kind === "hint" && m.meta?.level != null && ` · level ${m.meta.level}`}
              {m.meta?.source === "observer" && " · observer"}
            </div>
          );
        })()}
        {typeof m.meta?.reasoning === "string" && m.meta.reasoning && (
          <ThinkingBlock text={m.meta.reasoning} />
        )}
        {Array.isArray(m.meta?.plan)
          ? <PlanCard items={m.meta.plan as PlanItem[]}
              agent={m.meta.agent as string | undefined} />
          : <MarkdownView>{m.content}</MarkdownView>}
        {typeof suggestion?.command === "string" && (
          <div className="mt-2 rounded bg-black/40 p-2 font-mono text-xs text-accent whitespace-pre-wrap break-all">
            $ {suggestion.command}
          </div>
        )}
        {suggestion && actionId != null && !resolved && (
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="success" disabled={confirming}
              onClick={() => {
                setConfirming(true);
                void Promise.resolve(onConfirm(actionId, true))
                  .finally(() => setConfirming(false));
              }}>
              {confirming
                ? <Loader2 className="h-3 w-3 animate-spin" />
                : <Play className="h-3 w-3" />}
              {confirming ? "Running…" : "Run on Kali"}
            </Button>
            <Button size="sm" variant="secondary" disabled={confirming}
              onClick={() => onConfirm(actionId, false)}>
              <X className="h-3 w-3" /> Dismiss
            </Button>
          </div>
        )}
        {resolved && (
          <div className={cn("mt-1.5 text-[10px] font-medium uppercase tracking-wide",
            resolved === "confirmed" ? "text-success" : "text-muted")}>
            {resolved === "confirmed" ? "executed on Kali" : resolved === "rejected" ? "dismissed" : resolved}
          </div>
        )}
        {typeof m.meta?.agent_ref === "string" && onSelectAgent && (
          <button onClick={() => onSelectAgent(m.meta!.agent_ref as string)}
            className="mt-1.5 block text-[10px] font-medium uppercase tracking-wide text-primary hover:underline cursor-pointer">
            open {m.meta.agent_ref as string} feed →
          </button>
        )}
        <div className="mt-1 text-[10px] text-muted">
          {m.ts ? new Date(m.ts).toLocaleTimeString() : ""}
        </div>
      </div>
    </div>
  );
});
