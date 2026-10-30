import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";

/** Scrolling deploy/reset log — shown while a range builds (can take many minutes). */
export function DeployLog({ lines, state, fill }: { lines: string[]; state?: string; fill?: boolean }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "auto" }); }, [lines.length]);

  return (
    <div className={`flex flex-col bg-black ${fill ? "h-full" : "flex-1"}`}>
      <div className="flex items-center gap-2 border-b border-border px-3 py-2 text-xs text-muted">
        {state && state !== "ready" && state !== "active" && state !== "failed" && (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
        )}
        {state ? `range ${state}` : "deploy log"}
      </div>
      <div className="flex-1 overflow-auto p-3 font-mono text-[11px] leading-relaxed text-muted">
        {lines.map((l, i) => <div key={i} className="whitespace-pre-wrap">{l}</div>)}
        {!lines.length && <div className="text-muted/60">No output yet…</div>}
        <div ref={endRef} />
      </div>
    </div>
  );
}
