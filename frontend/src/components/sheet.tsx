import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen, CheckCircle2, ChevronDown, Circle, Flag, Network, Server,
} from "lucide-react";
import { api, type QuestDetail, type Session, type SessionFlags, type WsEvent } from "@/lib/api";
import { hostIp, topologyToMermaid } from "@/lib/netmap";
import { MermaidDiagram } from "@/components/mermaid";
import { MarkdownView } from "@/components/markdown";
import { Badge } from "@/components/ui";
import { cn } from "@/lib/utils";

/** Collapsible reference panel next to the console — network map, hosts,
 *  quest + track cheatsheets, flag tracker. Purely spoiler-free reference. */
export function SheetPanel({ sessionId, events }: { sessionId: number; events: WsEvent[] }) {
  const qc = useQueryClient();
  const { data: session } = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.get<Session>(`/api/sessions/${sessionId}`),
  });
  const { data: quest } = useQuery({
    queryKey: ["quest", session?.quest_id],
    queryFn: () => api.get<QuestDetail>(`/api/quests/${session!.quest_id}`),
    enabled: !!session?.quest_id,
  });
  const { data: flags } = useQuery({
    queryKey: ["session-flags", sessionId],
    queryFn: () => api.get<SessionFlags>(`/api/sessions/${sessionId}/flags`),
  });

  // keep the flag tracker live even when the Objectives tab isn't mounted
  useEffect(() => {
    const ev = events[events.length - 1];
    if (ev && (ev.type === "flag" || ev.type === "solved")) {
      qc.invalidateQueries({ queryKey: ["session-flags", sessionId] });
    }
  }, [events, sessionId, qc]);

  const chart = useMemo(() => topologyToMermaid(quest?.topology), [quest?.topology]);
  const vms = quest?.topology?.vms ?? [];

  return (
    <div className="flex h-full flex-col bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2 text-sm font-medium">
        <BookOpen className="h-4 w-4 text-primary" /> Reference
      </div>
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
        <Section icon={Network} title="Network map" defaultOpen>
          {quest ? <MermaidDiagram code={chart} /> : <div className="text-xs text-muted">Loading…</div>}
        </Section>

        <Section icon={Server} title={`Hosts (${vms.length + 1})`}>
          <div className="space-y-1">
            <HostRow name="kali" ip="10.x.10.5" sub="attacker" accent />
            {vms.map((vm) => (
              <HostRow key={vm.name} name={vm.name}
                ip={hostIp(vm.vlan, vm.ip_last_octet)}
                sub={[vm.windows || vm.domain ? "windows" : "linux",
                  vm.ram_gb ? `${vm.ram_gb}G` : null,
                  vm.cpus ? `${vm.cpus}cpu` : null,
                ].filter(Boolean).join(" · ")}
                roles={vm.roles} />
            ))}
          </div>
        </Section>

        <Section icon={Flag} title={`Flags ${flags ? `${flags.solved}/${flags.total}` : ""}`} defaultOpen>
          <div className="space-y-1">
            {(flags?.flags ?? []).map((f) => (
              <div key={f.key} className="flex items-center gap-2 rounded-md bg-surface-2/50 px-2 py-1.5">
                {f.solved
                  ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" />
                  : <Circle className="h-3.5 w-3.5 shrink-0 text-muted" />}
                <span className={cn("min-w-0 flex-1 truncate text-xs",
                  f.solved && "text-muted line-through")}>{f.name}</span>
                <Badge variant="accent" className="shrink-0">{f.points}</Badge>
              </div>
            ))}
            {!flags?.flags.length && <div className="text-xs text-muted">No flags.</div>}
          </div>
        </Section>

        {!!quest?.cheatsheet_md && (
          <Section icon={BookOpen} title="Quest reference">
            <MdBody>{quest.cheatsheet_md}</MdBody>
          </Section>
        )}
        {!!quest?.track_cheatsheet_md && (
          <Section icon={BookOpen} title="Track reference">
            <MdBody>{quest.track_cheatsheet_md}</MdBody>
          </Section>
        )}
      </div>
    </div>
  );
}

function Section({ icon: Icon, title, defaultOpen, children }: {
  icon: React.ElementType; title: string; defaultOpen?: boolean; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <div className="rounded-lg border border-border">
      <button onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs font-medium text-muted hover:text-foreground cursor-pointer">
        <Icon className="h-3.5 w-3.5" />
        <span className="flex-1">{title}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", !open && "-rotate-90")} />
      </button>
      {open && <div className="border-t border-border/60 px-2.5 py-2">{children}</div>}
    </div>
  );
}

function HostRow({ name, ip, sub, roles, accent }: {
  name: string; ip: string; sub: string; roles?: string[]; accent?: boolean;
}) {
  return (
    <div className={cn("rounded-md px-2 py-1.5", accent ? "bg-primary/10" : "bg-surface-2/50")}>
      <div className="flex items-center justify-between gap-2">
        <span className={cn("font-mono text-xs font-medium", accent && "text-primary")}>{name}</span>
        <span className="font-mono text-[11px] text-muted">{ip}</span>
      </div>
      <div className="mt-0.5 text-[11px] text-muted">{sub}</div>
      {!!roles?.length && (
        <div className="mt-0.5 truncate font-mono text-[10px] text-muted/70">
          {roles.join(", ")}
        </div>
      )}
    </div>
  );
}

function MdBody({ children }: { children: string }) {
  return (
    <div className="text-xs leading-relaxed text-muted
      [&_h1]:text-sm [&_h1]:font-semibold [&_h1]:text-foreground [&_h1]:mt-2 [&_h1]:mb-1
      [&_h2]:text-xs [&_h2]:font-semibold [&_h2]:text-foreground [&_h2]:mt-2 [&_h2]:mb-1
      [&_h3]:text-xs [&_h3]:font-semibold [&_h3]:text-foreground
      [&_code]:rounded [&_code]:bg-surface-2 [&_code]:px-1 [&_code]:text-accent [&_code]:text-[11px]
      [&_pre]:bg-surface-2 [&_pre]:rounded [&_pre]:p-2 [&_pre]:my-1 [&_pre]:overflow-x-auto
      [&_ul]:ml-3.5 [&_ul]:list-disc [&_ol]:ml-3.5 [&_ol]:list-decimal [&_li]:my-0.5">
      <MarkdownView>{children}</MarkdownView>
    </div>
  );
}
