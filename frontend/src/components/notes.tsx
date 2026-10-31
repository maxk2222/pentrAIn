import { useEffect, useRef, useState } from "react";
import { Check, Copy, NotebookPen } from "lucide-react";
import { IconButton } from "@/components/ui";

const keyFor = (sessionId: number) => `pentrain-notes-${sessionId}`;

/** Per-session scratchpad — bottom drawer under the console. Content lives in
 *  localStorage keyed by session, survives reloads and tab remounts. */
export function NotesPanel({ sessionId, open, onToggle }: {
  sessionId: number; open: boolean; onToggle: () => void;
}) {
  const [text, setText] = useState(() => localStorage.getItem(keyFor(sessionId)) ?? "");
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const textRef = useRef(text);
  textRef.current = text;

  // session switch → load that session's notes
  useEffect(() => {
    setText(localStorage.getItem(keyFor(sessionId)) ?? "");
  }, [sessionId]);

  function onChange(v: string) {
    setText(v);
    setSaved(false);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      localStorage.setItem(keyFor(sessionId), v);
      setSaved(true);
    }, 500);
  }

  // flush on unmount so nothing typed in the last 500ms is lost
  useEffect(() => () => {
    clearTimeout(timer.current);
    localStorage.setItem(keyFor(sessionId), textRef.current);
  }, [sessionId]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable (non-secure context) */ }
  }

  return (
    <div className="flex flex-col border-t border-border bg-surface">
      <div className="flex h-7 w-full items-center gap-2 px-3 text-xs text-muted">
        <button onClick={onToggle}
          className="flex flex-1 items-center gap-2 text-left hover:text-foreground cursor-pointer">
          <NotebookPen className="h-3.5 w-3.5" />
          <span className="font-medium">Notes</span>
          {text.trim() && !open && (
            <span className="text-[10px] text-muted/60">— {text.trim().split("\n").length} lines saved</span>
          )}
          <span className="ml-auto text-[10px]">{open ? "▾" : "▴"}</span>
        </button>
        {open && (
          <>
            {saved && <span className="flex items-center gap-0.5 text-[10px] text-success"><Check className="h-3 w-3" /> saved</span>}
            <IconButton size="sm" icon={copied ? Check : Copy} label="Copy notes"
              onClick={copy} className={copied ? "text-success hover:text-success" : undefined} />
          </>
        )}
      </div>
      {open && (
        <textarea
          value={text}
          onChange={(e) => onChange(e.target.value)}
          placeholder={"Scratchpad for this session — creds found, IPs, commands, dead ends.\nSaved locally, per session."}
          spellCheck={false}
          className="h-44 w-full resize-none border-0 bg-surface-2/40 px-3 py-2 font-mono text-xs leading-relaxed text-foreground placeholder:text-muted/50 focus-visible:outline-none"
        />
      )}
    </div>
  );
}
