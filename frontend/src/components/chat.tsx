import { memo, useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Bot, Lightbulb, Loader2, Play, Radio, Terminal, User, X } from "lucide-react";
import { api, type ChatMessage, type WsEvent } from "@/lib/api";
import { Button } from "@/components/ui";
import { MarkdownView } from "@/components/markdown";
import { cn } from "@/lib/utils";

type Resolved = "confirmed" | "rejected" | "error" | string;

interface Draft { text: string; reasoning: string; kind: string; done: boolean }

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

export function ChatPanel({ sessionId, events }: { sessionId: number; events: WsEvent[] }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [thinking, setThinking] = useState(false);
  const [sendError, setSendError] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [activity, setActivity] = useState<{ text: string; since: number } | null>(null);
  const [now, setNow] = useState(0);
  const [atBottom, setAtBottom] = useState(true);
  const [unseen, setUnseen] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const thinkTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const draftTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const composerRef = useRef<HTMLTextAreaElement>(null);

  const removeDraft = useCallback((id: string) => {
    clearTimeout(draftTimers.current.get(id));
    draftTimers.current.delete(id);
    setDrafts((d) => { const n = { ...d }; delete n[id]; return n; });
  }, []);

  useEffect(() => () => {
    clearTimeout(thinkTimer.current);
    draftTimers.current.forEach(clearTimeout);
  }, []);

  const { data: messages } = useQuery({
    queryKey: ["chat", sessionId],
    queryFn: () => api.get<ChatMessage[]>(`/api/sessions/${sessionId}/chat`),
  });

  // live events: coach messages arrive over the session WS
  useEffect(() => {
    const ev = events[events.length - 1];
    if (!ev) return;
    if (ev.type === "coach_message" && ev.data) {
      const msg = ev.data as ChatMessage;
      qc.setQueryData<ChatMessage[]>(["chat", sessionId], (old) => {
        if (old?.some((m) => m.id === msg.id)) return old;
        return [...(old ?? []), { ...msg, ts: msg.ts ?? new Date().toISOString() }];
      });
      if (msg.role === "coach") setThinking(false);
      // the persisted message replaces its streaming draft atomically
      const did = msg.meta?.draft_id;
      if (typeof did === "string") removeDraft(did);
    }
    // streaming drafts: cumulative content relayed while the LLM generates
    if (ev.type === "coach_stream" && ev.data?.draft_id) {
      const { draft_id, content = "", reasoning = "", kind = "chat", done } = ev.data as {
        draft_id: string; content?: string; reasoning?: string;
        kind?: string; done?: boolean;
      };
      setDrafts((d) => ({ ...d, [draft_id]: { text: content, reasoning, kind, done: !!done } }));
      if (done) {
        // the real message may arrive a beat later — grace period, then drop
        clearTimeout(draftTimers.current.get(draft_id));
        draftTimers.current.set(draft_id, setTimeout(() => removeDraft(draft_id), 2500));
      }
    }
    // 'coach working' status — emitted while slow actions (exec, screen
    // analysis, flag checks) are in flight; cleared by active:false
    if (ev.type === "coach_activity" && ev.data) {
      const { active, text = "" } = ev.data as { active: boolean; text?: string };
      setActivity(active ? { text, since: Date.now() } : null);
    }
    // suggestion confirm/reject → mark the matching suggestion message resolved
    if (ev.type === "coach_action" && ev.data?.status && ev.data.id) {
      const { id, status } = ev.data as { id: number; status: string };
      if (status === "confirmed" || status === "rejected" || status === "error") {
        markResolved(id, status);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events, sessionId, qc, removeDraft]);

  // tick the elapsed counter once a second while the coach is working;
  // 5min staleness cap covers a coach dying mid-action
  useEffect(() => {
    if (!activity) return;
    setNow(Date.now());
    const iv = setInterval(() => {
      const n = Date.now();
      setNow(n);
      if (n - activity.since > 300_000) setActivity(null);
    }, 1000);
    return () => clearInterval(iv);
  }, [activity]);

  // smart autoscroll: follow the tail only while the user is already at the bottom
  const draftSize = Object.values(drafts).reduce((a, d) => a + d.text.length, 0);
  useEffect(() => {
    if (atBottom) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    else setUnseen((n) => n + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages?.length, draftSize]);

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
        <span>Coach <span className="ml-1 text-xs font-normal text-muted">adaptive hints</span></span>
        {thinking && (
          <span className="flex items-center gap-1 text-xs text-muted">
            <Radio className="h-3 w-3 animate-pulse text-primary" /> thinking…
          </span>
        )}
      </div>
      <div ref={scrollRef} onScroll={onScroll} className="flex-1 space-y-3 overflow-auto p-3">
        {(messages ?? []).map((m) => (
          <Message key={m.id} m={m} onConfirm={confirmAction} />
        ))}
        {Object.entries(drafts).map(([id, d]) => (
          <div key={id} className="flex gap-2">
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
        {!messages?.length && !thinking && (
          <p className="p-2 text-sm text-muted">
            The coach will chime in as you work. Ask questions anytime — it renders
            Markdown, code blocks and diagrams.
          </p>
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
            placeholder="Ask the coach… (Shift+Enter for newline)"
            maxLength={8000}
            className="max-h-[120px] min-w-0 flex-1 resize-none rounded-md border border-border bg-surface-2 px-3 py-2 text-sm outline-none placeholder:text-muted focus:border-primary/60" />
          {text.length > 7200 && (
            <span className="pb-1.5 text-[10px] text-muted">{text.length}/8000</span>
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

const KIND_STYLE: Record<string, { label: string; cls: string; iconCls: string }> = {
  suggestion: { label: "suggested command", cls: "border border-accent/40 bg-accent/10", iconCls: "bg-accent/15 text-accent" },
  action_report: { label: "coach action", cls: "border border-warning/40 bg-warning/10", iconCls: "bg-warning/15 text-warning" },
  hint: { label: "hint", cls: "border border-accent/40 bg-accent/5", iconCls: "bg-accent/15 text-accent" },
  nudge: { label: "", cls: "bg-surface-2", iconCls: "bg-primary/20 text-primary" },
};

// memoized — a new WS event would otherwise re-parse every message's markdown
const Message = memo(function Message({ m, onConfirm }: {
  m: ChatMessage; onConfirm: (actionId: number, accept: boolean) => void;
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
            : m.kind === "suggestion" || m.kind === "action_report"
              ? <Terminal className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />)
          : <User className="h-3.5 w-3.5" />}
      </div>
      <div className={cn("max-w-[85%] rounded-lg px-3 py-2 text-sm leading-relaxed",
        m.role === "user" ? "bg-primary/15" : style.cls)}>
        {style.label && (
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            {style.label}
            {m.kind === "hint" && m.meta?.level != null && ` · level ${m.meta.level}`}
          </div>
        )}
        {typeof m.meta?.reasoning === "string" && m.meta.reasoning && (
          <ThinkingBlock text={m.meta.reasoning} />
        )}
        <MarkdownView>{m.content}</MarkdownView>
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
        <div className="mt-1 text-[10px] text-muted">
          {m.ts ? new Date(m.ts).toLocaleTimeString() : ""}
        </div>
      </div>
    </div>
  );
});
