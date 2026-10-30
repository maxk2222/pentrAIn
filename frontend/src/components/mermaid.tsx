import { useEffect, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";

let mermaidPromise: Promise<typeof import("mermaid").default> | null = null;

/** Lazy-load mermaid (~1.5 MB) — only when a diagram is actually on screen. */
function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((mod) => {
      // a failed chunk fetch would otherwise poison every later diagram
      const mermaid = mod.default;
      mermaid.initialize({
        startOnLoad: false,
        theme: "dark",
        // LLM-generated labels → strict sanitization is mandatory
        securityLevel: "strict",
        fontFamily: "ui-monospace, monospace",
        themeVariables: {
          background: "transparent",
          primaryColor: "#171e2a",
          primaryBorderColor: "#3b82f6",
          primaryTextColor: "#e6edf6",
          lineColor: "#8b98ad",
          secondaryColor: "#232c3d",
          tertiaryColor: "#11161f",
        },
      });
      return mermaid;
    });
    mermaidPromise.catch(() => { mermaidPromise = null; });
  }
  return mermaidPromise;
}

let idSeq = 0;

export function MermaidDiagram({ code }: { code: string }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    const src = code.trim();
    if (src.length > 12000) { setError("diagram source too large"); return; }
    const id = `pnt-${++idSeq}`;
    loadMermaid()
      .then(async (mermaid) => {
        const { svg } = await mermaid.render(id, src);
        if (!cancelled && hostRef.current) hostRef.current.innerHTML = svg;
      })
      .catch((e: unknown) => {
        // mermaid leaves a stray #d<id> error node in <body> on parse failure
        document.getElementById(`d${id}`)?.remove();
        document.getElementById(id)?.remove();
        if (!cancelled) setError(e instanceof Error ? e.message : "diagram error");
      });
    return () => { cancelled = true; };
  }, [code]);

  if (error) {
    return (
      <div className="rounded-md border border-warning/30 bg-surface-2 p-2">
        <div className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wide text-warning">
          <AlertTriangle className="h-3 w-3" /> diagram failed to render
        </div>
        <pre className="overflow-x-auto font-mono text-xs text-muted whitespace-pre">{code}</pre>
      </div>
    );
  }
  return (
    <div ref={hostRef}
      className="my-2 overflow-x-auto rounded-md border border-border bg-surface-2/60 p-2 [&_svg]:mx-auto [&_svg]:max-w-full" />
  );
}
