/** Findings + report panel — typed findings the agent recorded via
 * record_finding (replayed backend-side, so the list survives coach
 * restarts) plus the assembled markdown report for engagement runs. */
import { useQuery } from "@tanstack/react-query";
import { Bug, FileText } from "lucide-react";
import { api, type Finding } from "@/lib/api";
import { Badge, Tabs } from "@/components/ui";
import { MarkdownView } from "@/components/markdown";
import { useState } from "react";

const SEV_VARIANT: Record<string, "danger" | "warning" | "default" | "outline"> = {
  critical: "danger", high: "danger", medium: "warning", low: "default",
  info: "outline",
};
const STATUS_VARIANT: Record<string, "success" | "warning" | "outline"> = {
  confirmed: "success", candidate: "warning", rejected: "outline",
};

export function FindingsPanel({ sessionId }: { sessionId: number }) {
  const [tab, setTab] = useState<"findings" | "report">("findings");
  const { data } = useQuery({
    queryKey: ["findings", sessionId],
    queryFn: () => api.get<{ findings: Finding[] }>(
      `/api/sessions/${sessionId}/findings`),
    refetchInterval: 5000,
  });
  const { data: rep } = useQuery({
    queryKey: ["report", sessionId],
    queryFn: () => api.get<{ markdown: string }>(
      `/api/sessions/${sessionId}/report`),
    enabled: tab === "report",
    refetchInterval: 8000,
  });
  const findings = data?.findings ?? [];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs className="m-2" active={tab} onChange={(t) => setTab(t as never)}
        tabs={[
          { id: "findings", label: <span className="flex items-center gap-1"><Bug className="h-3.5 w-3.5" /> Findings ({findings.length})</span> },
          { id: "report", label: <span className="flex items-center gap-1"><FileText className="h-3.5 w-3.5" /> Report</span> },
        ]} />
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {tab === "findings" && (
          findings.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted">
              No findings recorded yet — the agent writes them via
              record_finding as it validates surfaces.
            </p>
          ) : (
            <ul className="space-y-2">
              {findings.map((f) => (
                <li key={f.id} className="rounded border border-border bg-surface p-2.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-muted">{f.id}</span>
                    <Badge variant={SEV_VARIANT[f.sev] ?? "default"}>{f.sev}</Badge>
                    <Badge variant={STATUS_VARIANT[f.status] ?? "default"}>{f.status}</Badge>
                    <span className="ml-auto font-mono text-[10px] text-muted">
                      {[f.host, f.owner !== "main" ? `@${f.owner}` : ""]
                        .filter(Boolean).join(" ")}
                    </span>
                  </div>
                  <div className="mt-1 text-xs font-medium">{f.title}</div>
                  {f.evidence && (
                    <div className="mt-1 font-mono text-[11px] leading-snug text-muted">
                      {f.evidence}
                    </div>)}
                  {f.next && (
                    <div className="mt-1 text-[11px] text-accent">→ {f.next}</div>)}
                </li>
              ))}
            </ul>
          ))}
        {tab === "report" && (
          rep?.markdown
            ? <MarkdownView>{rep.markdown}</MarkdownView>
            : <p className="py-6 text-center text-xs text-muted">Loading…</p>)}
      </div>
    </div>
  );
}
