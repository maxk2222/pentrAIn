import { isValidElement, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";
import { MermaidDiagram } from "@/components/mermaid";
import { cn } from "@/lib/utils";

function extractText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (isValidElement(node)) {
    return extractText((node.props as { children?: ReactNode }).children);
  }
  return "";
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="group/code relative my-2 overflow-hidden rounded-md border border-border bg-black/50">
      <div className="flex items-center justify-between border-b border-border px-2.5 py-1">
        <span className="font-mono text-[10px] uppercase tracking-wide text-muted">
          {lang || "text"}
        </span>
        <button
          onClick={() => {
            void navigator.clipboard?.writeText(code);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className="text-muted opacity-0 transition-opacity hover:text-foreground group-hover/code:opacity-100 cursor-pointer"
          title="Copy">
          {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
        </button>
      </div>
      <pre className="overflow-x-auto p-2.5 font-mono text-xs leading-relaxed text-foreground">
        <code>{code}</code>
      </pre>
    </div>
  );
}

/**
 * Shared GFM renderer — chat messages, briefings, defense notes.
 * ```mermaid fences render as diagrams; other fences get styled code blocks.
 */
export function MarkdownView({ children, className }: {
  children: string; className?: string;
}) {
  return (
    <div className={cn("ptn-md", className)}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre: (props) => {
            const child = props.children;
            const codeClass = isValidElement(child)
              ? String((child.props as { className?: string }).className ?? "") : "";
            const lang = /language-(\w+)/.exec(codeClass)?.[1] ?? "";
            const code = extractText(child).replace(/\n$/, "");
            if (lang === "mermaid") return <MermaidDiagram code={code} />;
            return <CodeBlock lang={lang} code={code} />;
          },
          code: (props) => (
            <code className="rounded bg-black/40 px-1 py-0.5 font-mono text-[0.85em] text-accent">
              {props.children}
            </code>
          ),
          a: (props) => (
            <a {...props} target="_blank" rel="noreferrer"
              className="text-accent underline decoration-accent/40 hover:decoration-accent" />
          ),
          table: (props) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse text-xs" {...props} />
            </div>
          ),
          th: (props) => <th className="border-b border-border px-2 py-1 text-left font-semibold" {...props} />,
          td: (props) => <td className="border-b border-border/50 px-2 py-1" {...props} />,
          ul: (props) => <ul className="my-1.5 list-disc space-y-0.5 pl-5" {...props} />,
          ol: (props) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5" {...props} />,
          p: (props) => <p className="my-1.5 first:mt-0 last:mb-0" {...props} />,
          blockquote: (props) => (
            <blockquote className="my-2 border-l-2 border-primary/50 pl-3 text-muted" {...props} />
          ),
          h1: (props) => <h1 className="mb-1 mt-3 text-base font-semibold" {...props} />,
          h2: (props) => <h2 className="mb-1 mt-3 text-sm font-semibold" {...props} />,
          h3: (props) => <h3 className="mb-0.5 mt-2 text-sm font-semibold" {...props} />,
          hr: () => <hr className="my-3 border-border" />,
        }}>
        {children}
      </Markdown>
    </div>
  );
}
