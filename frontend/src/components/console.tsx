import { useCallback, useEffect, useRef, useState } from "react";
import RFB from "@novnc/novnc";
import { api, wsUrl } from "@/lib/api";
import { ClipboardCopy, ClipboardPaste, Info, Maximize2, RefreshCw, X } from "lucide-react";
import { IconButton } from "@/components/ui";

type Status = "connecting" | "connected" | "disconnected" | "error" | "mock";
type Pop = "creds" | "paste" | "clip" | null;

const KALI_CREDS = { user: "kali", password: "kali" };

/** Type text into the console as real keystrokes. PVE's VNC can't relay
 * ClientCutText (no vdagent/QEMU clipboard channel), so paste = key events.
 * QEMU maps latin keysyms → scancode+shift itself; non-latin gets the
 * X unicode keysym convention. */
async function typeText(rfb: RFB, text: string, signal: { stop: boolean },
                        onProgress: (done: number, total: number) => void) {
  const keysym = (ch: string): number => {
    if (ch === "\n" || ch === "\r") return 0xff0d;      // Return
    if (ch === "\t") return 0xff09;                    // Tab
    const cp = ch.codePointAt(0)!;
    return cp < 0x100 ? cp : 0x01000000 | cp;          // latin / unicode keysym
  };
  const chars = [...text];
  const total = chars.length;
  for (let i = 0; i < chars.length; i++) {
    if (signal.stop) return;
    rfb.sendKey(keysym(chars[i]), "");
    onProgress(i + 1, total);
    // keep the upstream pipe honest — ~160 keys/s, big pastes stay reliable
    if (i % 8 === 7) await new Promise((r) => setTimeout(r, 50));
    else await new Promise((r) => setTimeout(r, 6));
  }
}

/**
 * Kali desktop via Proxmox VNC-over-WebSocket, proxied through our backend.
 * Flow: GET /sessions/{id}/console → {ticket} → RFB to /api/console/{id}
 * with the ticket as the VNC password (same mechanism as the PVE web UI).
 */
export function ConsoleView({ sessionId, vmid }: { sessionId?: number; vmid?: number }) {
  // vmid mode = admin console for a standalone VM (template builder); the
  // session-scoped guest clipboard route doesn't apply there.
  const ticketPath = vmid ? `/api/admin/console/vm/${vmid}/ticket`
    : `/api/sessions/${sessionId}/console`;
  const wsPath = vmid ? `/api/console/vm/${vmid}` : `/api/console/${sessionId}`;
  const clipPath = vmid ? null : `/api/sessions/${sessionId}/console/clipboard`;
  const hostRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFB | null>(null);
  const typeCtl = useRef<{ stop: boolean }>({ stop: false });
  const [status, setStatus] = useState<Status>("connecting");
  const [detail, setDetail] = useState("");
  const [nonce, setNonce] = useState(0);
  const [pop, setPop] = useState<Pop>(null);
  const [pasteText, setPasteText] = useState("");
  const [typing, setTyping] = useState<{ done: number; total: number } | null>(null);
  const [clip, setClip] = useState<string | null>(null);
  const [clipLoading, setClipLoading] = useState(false);

  const inject = useCallback(async (text: string) => {
    const rfb = rfbRef.current;
    if (!rfb || !text) return;
    typeCtl.current.stop = false;
    setTyping({ done: 0, total: [...text].length });
    setPop(null);
    try {
      await typeText(rfb, text, typeCtl.current, (done, t) => setTyping({ done, total: t }));
    } finally {
      setTyping(null);
    }
  }, []);

  const fetchClip = useCallback(async () => {
    if (!clipPath) return;
    setClipLoading(true); setClip(null); setPop("clip");
    try {
      const r = await api.get<{ text?: string; mock?: boolean }>(clipPath);
      setClip(r.mock ? "(mock engine — no guest clipboard)" : (r.text ?? ""));
    } catch (e) {
      setClip(`(failed: ${e instanceof Error ? e.message : "unavailable"})`);
    } finally {
      setClipLoading(false);
    }
  }, [clipPath]);

  useEffect(() => {
    let rfb: RFB | null = null;
    let cancelled = false;

    async function connect() {
      setStatus("connecting"); setDetail("");
      try {
        const t = await api.get<{ ticket?: string; mock?: boolean; error?: string }>(ticketPath);
        if (cancelled || !hostRef.current) return;
        if (t.mock) { setStatus("mock"); return; }
        if (!t.ticket) { setStatus("error"); setDetail(t.error ?? "no console ticket"); return; }

        rfb = new RFB(hostRef.current!, wsUrl(wsPath), {
          credentials: { password: t.ticket },
        });
        rfbRef.current = rfb;
        rfb.viewOnly = false;
        rfb.scaleViewport = true;
        rfb.background = "#000";

        rfb.addEventListener("connect", () => { if (!cancelled) setStatus("connected"); });
        rfb.addEventListener("disconnect", (e: CustomEvent) => {
          if (cancelled) return;
          const d = e.detail as { clean?: boolean; reason?: string };
          setStatus("disconnected");
          setDetail(d?.reason ?? "");
        });
        rfb.addEventListener("credentialsrequired", () => {
          if (!cancelled) { setStatus("error"); setDetail("console credentials expired — reconnect"); }
        });
        rfb.addEventListener("securityfailure", (e: CustomEvent) => {
          const d = e.detail as { status?: number; reason?: string };
          setStatus("error"); setDetail(`security failure: ${d?.reason ?? d?.status ?? "unknown"}`);
        });
      } catch (e) {
        if (!cancelled) { setStatus("error"); setDetail(e instanceof Error ? e.message : "console unavailable"); }
      }
    }

    // Cmd/Ctrl+V (or context-menu paste) typed into the guest as keystrokes —
    // the DOM paste event exposes clipboardData without a clipboard permission.
    const onPaste = (e: ClipboardEvent) => {
      if (!hostRef.current || !e.target || !hostRef.current.contains(e.target as Node)) return;
      const text = e.clipboardData?.getData("text");
      if (!text) return;
      e.preventDefault();
      void inject(text.slice(0, 8192));
    };
    document.addEventListener("paste", onPaste);

    connect();
    return () => {
      cancelled = true;
      typeCtl.current.stop = true;
      document.removeEventListener("paste", onPaste);
      try { rfb?.disconnect(); } catch { /* noop */ }
      rfbRef.current = null;
    };
  }, [sessionId, vmid, nonce, inject, ticketPath, wsPath]);

  return (
    <div className="relative flex h-full flex-col bg-black">
      <div className="flex items-center justify-between border-b border-border bg-surface px-3 py-1.5">
        <div className="flex items-center gap-2 text-xs">
          <span className={`h-2 w-2 rounded-full ${
            status === "connected" ? "bg-success"
            : status === "connecting" ? "bg-warning animate-pulse" : "bg-danger"}`} />
          <span className="text-muted capitalize">{status === "mock" ? "mock console" : status}</span>
          {typing && (
            <span className="text-accent">typing {typing.done}/{typing.total}…</span>
          )}
          {detail && !typing && <span className="truncate text-danger">— {detail}</span>}
        </div>
        <div className="relative flex items-center gap-1">
          <IconButton size="sm" icon={ClipboardPaste} label="Paste as keystrokes"
            onClick={() => setPop(pop === "paste" ? null : "paste")} />
          {clipPath && (
            <IconButton size="sm" icon={ClipboardCopy} label="Read guest clipboard"
              onClick={fetchClip} />
          )}
          <IconButton size="sm" icon={Info} label="Kali login"
            onClick={() => setPop(pop === "creds" ? null : "creds")} />
          <IconButton size="sm" icon={RefreshCw} label="Reconnect"
            onClick={() => setNonce((n) => n + 1)} />
          <IconButton size="sm" icon={Maximize2} label="Fullscreen"
            onClick={() => hostRef.current?.requestFullscreen?.()} />

          {pop && (
            <>
              <div className="fixed inset-0 z-20" onClick={() => setPop(null)} />
              <div className="absolute right-0 top-8 z-30 w-80 rounded-lg border border-border bg-surface-2 p-3 shadow-xl">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-medium">
                    {pop === "creds" ? "Kali login"
                     : pop === "paste" ? "Paste as keystrokes" : "Guest clipboard"}
                  </span>
                  <IconButton size="sm" icon={X} label="Close" onClick={() => setPop(null)} />
                </div>

                {pop === "creds" && (
                  <div className="space-y-2 text-xs">
                    <div className="flex items-center justify-between rounded bg-surface px-2 py-1.5 font-mono">
                      <span>user: {KALI_CREDS.user}</span>
                      <button className="text-accent hover:underline"
                        onClick={() => void navigator.clipboard?.writeText(KALI_CREDS.user)}>copy</button>
                    </div>
                    <div className="flex items-center justify-between rounded bg-surface px-2 py-1.5 font-mono">
                      <span>pass: {KALI_CREDS.password}</span>
                      <button className="text-accent hover:underline"
                        onClick={() => void navigator.clipboard?.writeText(KALI_CREDS.password)}>copy</button>
                    </div>
                    <p className="text-muted">
                      Stock Ludus Kali template — <code>sudo</code> uses the same password.
                    </p>
                  </div>
                )}

                {pop === "paste" && (
                  <div className="space-y-2">
                    <textarea value={pasteText} onChange={(e) => setPasteText(e.target.value)}
                      rows={4} placeholder="Text to type into the console…"
                      className="w-full rounded bg-surface p-2 font-mono text-xs outline-none focus:ring-1 focus:ring-primary" />
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-muted">typed as keystrokes · ⌘V / Ctrl+V works too</span>
                      <button
                        className="rounded bg-primary px-2.5 py-1 text-xs font-medium text-white disabled:opacity-40"
                        disabled={!pasteText || status !== "connected"}
                        onClick={() => { void inject(pasteText.slice(0, 8192)); setPasteText(""); }}>
                        Type it in
                      </button>
                    </div>
                  </div>
                )}

                {pop === "clip" && (
                  <div className="space-y-2">
                    {clipLoading ? (
                      <div className="text-xs text-muted">reading via guest agent…</div>
                    ) : (
                      <>
                        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-surface p-2 font-mono text-xs">
                          {clip === "" ? "(empty)" : clip}
                        </pre>
                        <button
                          className="w-full rounded bg-surface px-2 py-1.5 text-xs text-accent hover:bg-border"
                          onClick={() => clip && void navigator.clipboard?.writeText(clip)}>
                          copy to local clipboard
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {status === "mock" ? (
        <div className="grid flex-1 place-items-center bg-surface">
          <div className="max-w-sm space-y-2 text-center">
            <div className="font-mono text-4xl text-primary">$_</div>
            <p className="text-sm text-muted">
              Mock engine — no real Kali console. Configure the Ludus/PVE engine
              in Settings to get a live desktop.
            </p>
          </div>
        </div>
      ) : (
        <>
          <div ref={hostRef} className="min-h-0 flex-1 [&>div]:h-full [&>div]:w-full" />
          {status !== "connected" && (
            <div className="pointer-events-none absolute inset-0 top-8 grid place-items-center bg-black/60">
              <div className="px-4 text-center text-sm text-muted">
                {status === "connecting" ? "Connecting to Kali desktop…"
                  : detail || "Console disconnected"}
              </div>
            </div>
          )}
          {typing && (
            <div className="absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-3 rounded-full border border-border bg-surface-2/95 px-4 py-1.5 text-xs">
              <span className="text-accent">typing {typing.done}/{typing.total}</span>
              <button className="text-danger hover:underline"
                onClick={() => { typeCtl.current.stop = true; }}>cancel</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
