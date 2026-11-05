/* AI Quest Builder — chat-driven quest authoring with autonomous
   verification. Left: conversation (questions, tool calls, drafts).
   Right: materialized quest + verify timeline with a live session link. */
import { Link, useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2, ExternalLink, Loader2, Paperclip, PlayCircle, Send,
  Sparkles, Wand2, XCircle,
} from "lucide-react";
import { api, type BuilderMessage, type BuilderSession } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { useEffect, useRef, useState } from "react";

const ACTIVE = new Set(["verifying"]);
const STATUS_BADGE: Record<string, { label: string; variant: "default" | "success" | "warning" | "danger" | "accent" }> = {
  chat: { label: "chat", variant: "default" },
  materialized: { label: "built", variant: "accent" },
  verifying: { label: "verifying", variant: "warning" },
  verified: { label: "verified", variant: "success" },
  "verified-partial": { label: "partial", variant: "warning" },
  failed: { label: "failed", variant: "danger" },
  interrupted: { label: "interrupted", variant: "danger" },
};

export function BuilderPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const bsId = id ? Number(id) : undefined;
  const [text, setText] = useState("");
  const [files, setFiles] = useState<{ name: string; content: string }[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data: sessions } = useQuery({
    queryKey: ["builder-sessions"],
    queryFn: () => api.get<BuilderSession[]>("/api/builder/sessions"),
    refetchInterval: 10_000,
  });
  const { data: bs } = useQuery({
    queryKey: ["builder", bsId],
    queryFn: () => api.get<BuilderSession>(`/api/builder/sessions/${bsId}`),
    enabled: bsId != null,
    refetchInterval: (q) =>
      q.state.data && ACTIVE.has(q.state.data.status) ? 4000 : 10_000,
  });
  const { data: msgs } = useQuery({
    queryKey: ["builder-msgs", bsId],
    queryFn: () =>
      api.get<BuilderMessage[]>(`/api/builder/sessions/${bsId}/messages`),
    enabled: bsId != null,
    refetchInterval: (q) => (bs && ACTIVE.has(bs.status) ? 4000 : 8000),
  });

  const create = useMutation({
    mutationFn: () =>
      api.post<BuilderSession>("/api/builder/sessions", { title: "" }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["builder-sessions"] });
      nav(`/builder/${s.id}`);
    },
  });
  const send = useMutation({
    mutationFn: () =>
      api.post<BuilderMessage>(`/api/builder/sessions/${bsId}/chat`, {
        text, attachments: files,
      }),
    onSuccess: () => {
      setText(""); setFiles([]);
      qc.invalidateQueries({ queryKey: ["builder-msgs", bsId] });
      qc.invalidateQueries({ queryKey: ["builder", bsId] });
    },
  });
  const verify = useMutation({
    mutationFn: () =>
      api.post<BuilderMessage>(`/api/builder/sessions/${bsId}/verify`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["builder", bsId] });
      qc.invalidateQueries({ queryKey: ["builder-msgs", bsId] });
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs?.length]);

  const attach = (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = Array.from(e.target.files ?? []).slice(0, 4);
    Promise.all(list.map(async (f) => ({
      name: f.name, content: (await f.text()).slice(0, 32_000),
    }))).then((r) => setFiles((cur) => [...cur, ...r].slice(0, 8)));
    e.target.value = "";
  };

  const busy = send.isPending || (bs ? ACTIVE.has(bs.status) : false);
  const badge = bs ? STATUS_BADGE[bs.status] ?? STATUS_BADGE.chat : null;

  return (
    <div className="flex h-full">
      {/* session list */}
      <aside className="flex w-56 shrink-0 flex-col border-r border-border">
        <div className="flex items-center justify-between p-3">
          <span className="text-sm font-semibold">Builds</span>
          <Button size="sm" variant="outline" onClick={() => create.mutate()}
            disabled={create.isPending}>
            <Sparkles className="h-3.5 w-3.5" /> New
          </Button>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto px-2 pb-2">
          {(sessions ?? []).map((s) => (
            <Link key={s.id} to={`/builder/${s.id}`}
              className={cn(
                "block truncate rounded-md px-2 py-1.5 text-sm hover:bg-surface-2",
                s.id === bsId && "bg-surface-2 font-medium")}>
              {s.title || `build #${s.id}`}
              <span className="ml-1 text-xs text-muted">· {s.status}</span>
            </Link>
          ))}
          {!sessions?.length && (
            <p className="px-2 py-4 text-xs text-muted">
              No builds yet — describe what you want to test.
            </p>
          )}
        </div>
      </aside>

      {!bs ? (
        <div className="flex flex-1 items-center justify-center p-10">
          <div className="max-w-md text-center">
            <Wand2 className="mx-auto h-10 w-10 text-primary" />
            <h1 className="mt-3 text-xl font-bold">AI Quest Builder</h1>
            <p className="mt-2 text-sm text-muted">
              Describe what you want to test — paste a Docker Compose, k8s
              manifest, or Proxmox setup and I'll turn it into a playable
              quest. The quest only counts as finished once the coach solves
              it fully autonomously.
            </p>
            <Button className="mt-4" onClick={() => create.mutate()}
              disabled={create.isPending}>
              <Sparkles className="h-4 w-4" /> Start a build
            </Button>
          </div>
        </div>
      ) : (
        <>
          {/* chat column */}
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {(msgs ?? []).map((m) => (
                <ChatBubble key={m.id} m={m} />
              ))}
              {send.isPending && (
                <div className="flex items-center gap-2 text-sm text-muted">
                  <Loader2 className="h-4 w-4 animate-spin" /> builder is
                  thinking / running tools…
                </div>
              )}
              <div ref={bottomRef} />
            </div>
            {/* composer */}
            <div className="border-t border-border p-3">
              {files.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1">
                  {files.map((f, i) => (
                    <Badge key={i} variant="outline" className="gap-1">
                      {f.name}
                      <button onClick={() =>
                        setFiles(files.filter((_, j) => j !== i))}>×</button>
                    </Badge>
                  ))}
                </div>
              )}
              <div className="flex items-end gap-2">
                <label className="cursor-pointer text-muted hover:text-fg">
                  <Paperclip className="h-5 w-5" />
                  <input type="file" multiple className="hidden"
                    onChange={attach}
                    accept=".yml,.yaml,.json,.toml,.conf,.cfg,.txt,.md,.py,.sh,.service,.env" />
                </label>
                <textarea
                  className="max-h-40 min-h-[38px] flex-1 resize-y rounded-md border border-border bg-surface-2 px-3 py-2 text-sm placeholder:text-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
                  placeholder={bs.status === "verifying"
                    ? "verification running — chat resumes after it finishes"
                    : "Describe the scenario, or paste a config to build from…"}
                  value={text} disabled={busy}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey))
                      send.mutate();
                  }} />
                <Button onClick={() => send.mutate()}
                  disabled={busy || !text.trim()}>
                  <Send className="h-4 w-4" />
                </Button>
              </div>
              {send.isError && (
                <p className="mt-1 text-xs text-danger">
                  {(send.error as Error).message}
                </p>
              )}
            </div>
          </div>

          {/* status / verify column */}
          <aside className="flex w-80 shrink-0 flex-col gap-3 overflow-y-auto border-l border-border p-3">
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle className="text-sm">Quest</CardTitle>
                {badge && <Badge variant={badge.variant}>{badge.label}</Badge>}
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {bs.quest_id ? (
                  <Link to={`/quests/${bs.quest_id}`}
                    className="flex items-center gap-1 font-mono text-primary hover:underline">
                    {bs.quest_id} <ExternalLink className="h-3 w-3" />
                  </Link>
                ) : (
                  <span className="text-muted">no draft yet</span>
                )}
                {bs.verify_session_id && (
                  <Link to={`/session/${bs.verify_session_id}`}
                    className="flex items-center gap-1 text-primary hover:underline">
                    verification session #{bs.verify_session_id}
                    <ExternalLink className="h-3 w-3" />
                  </Link>
                )}
                <div className="flex items-center gap-2 pt-1">
                  <Button size="sm" onClick={() => verify.mutate()}
                    disabled={verify.isPending || busy || !bs.quest_id}>
                    <PlayCircle className="h-4 w-4" />
                    {bs.status === "verifying" ? "Verifying…" : "Verify with coach"}
                  </Button>
                </div>
                <p className="text-xs text-muted">
                  Coach solves at autonomy 4 with subagents — up to 3
                  patch/reset iterations.
                </p>
              </CardContent>
            </Card>

            <Card className="flex-1">
              <CardHeader><CardTitle className="text-sm">Build log</CardTitle></CardHeader>
              <CardContent className="space-y-1.5">
                {(bs.log ?? []).slice().reverse().map((l, i) => (
                  <div key={i} className="text-xs">
                    <span className="text-muted">{l.ts.slice(11, 19)} </span>
                    <span className={cn(
                      l.kind === "verify" && "text-primary",
                      l.kind === "diagnose" && "text-warning",
                      l.kind === "draft" && "text-accent")}>
                      {l.msg}
                    </span>
                  </div>
                ))}
                {!bs.log?.length && (
                  <p className="text-xs text-muted">nothing yet</p>
                )}
              </CardContent>
            </Card>
          </aside>
        </>
      )}
    </div>
  );
}

function ChatBubble({ m }: { m: BuilderMessage }) {
  if (m.kind === "tool") {
    return (
      <div className="rounded-md border border-border/60 bg-surface-2/50 px-3 py-1.5 font-mono text-xs text-muted">
        ⚙ {m.content}
        {typeof m.meta?.result === "string" && m.meta.result && (
          <div className="mt-1 line-clamp-3 whitespace-pre-wrap opacity-70">
            {m.meta.result}
          </div>
        )}
      </div>
    );
  }
  if (m.role === "system" || m.kind === "status") {
    return (
      <div className="text-center text-xs text-muted">— {m.content} —</div>
    );
  }
  const mine = m.role === "user";
  const err = m.kind === "error";
  return (
    <div className={cn("flex", mine ? "justify-end" : "justify-start")}>
      <div className={cn(
        "max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm",
        mine ? "bg-primary/15 text-fg" : "bg-surface-2",
        err && "border border-danger/40",
        m.kind === "draft" && "border border-accent/40")}>
        {m.kind === "draft" && (
          <Badge variant="accent" className="mb-1">draft</Badge>
        )}
        {err && <XCircle className="mr-1 inline h-3.5 w-3.5 text-danger" />}
        {m.kind === "draft" && m.content.includes("```") && m.role === "assistant"
          ? <DraftContent text={m.content} />
          : m.content}
      </div>
    </div>
  );
}

function DraftContent({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const pre = text.split("```draft")[0].trim();
  return (
    <div>
      {pre && <p className="mb-1">{pre}</p>}
      <button className="flex items-center gap-1 text-xs text-primary hover:underline"
        onClick={() => setOpen(!open)}>
        <CheckCircle2 className="h-3 w-3" />
        {open ? "hide draft spec" : "show draft spec"}
      </button>
      {open && (
        <pre className="mt-1 max-h-72 overflow-auto rounded bg-surface p-2 font-mono text-xs">
          {text}
        </pre>
      )}
    </div>
  );
}
