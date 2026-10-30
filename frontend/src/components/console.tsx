import { useEffect, useRef, useState } from "react";
import RFB from "@novnc/novnc";
import { api, wsUrl } from "@/lib/api";
import { Maximize2, RefreshCw } from "lucide-react";

type Status = "connecting" | "connected" | "disconnected" | "error" | "mock";

/**
 * Kali desktop via Proxmox VNC-over-WebSocket, proxied through our backend.
 * Flow: GET /sessions/{id}/console → {ticket} → RFB to /api/console/{id}
 * with the ticket as the VNC password (same mechanism as the PVE web UI).
 */
export function ConsoleView({ sessionId }: { sessionId: number }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFB | null>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const [detail, setDetail] = useState("");
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let rfb: RFB | null = null;
    let cancelled = false;

    async function connect() {
      setStatus("connecting"); setDetail("");
      try {
        const t = await api.get<{ ticket?: string; mock?: boolean; error?: string }>(
          `/api/sessions/${sessionId}/console`);
        if (cancelled || !hostRef.current) return;
        if (t.mock) { setStatus("mock"); return; }
        if (!t.ticket) { setStatus("error"); setDetail(t.error ?? "no console ticket"); return; }

        rfb = new RFB(hostRef.current!, wsUrl(`/api/console/${sessionId}`), {
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

    connect();
    return () => {
      cancelled = true;
      try { rfb?.disconnect(); } catch { /* noop */ }
      rfbRef.current = null;
    };
  }, [sessionId, nonce]);

  return (
    <div className="relative flex h-full flex-col bg-black">
      <div className="flex items-center justify-between border-b border-border bg-surface px-3 py-1.5">
        <div className="flex items-center gap-2 text-xs">
          <span className={`h-2 w-2 rounded-full ${
            status === "connected" ? "bg-success"
            : status === "connecting" ? "bg-warning animate-pulse" : "bg-danger"}`} />
          <span className="text-muted capitalize">{status === "mock" ? "mock console" : status}</span>
          {detail && <span className="truncate text-danger">— {detail}</span>}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setNonce((n) => n + 1)}
            className="rounded p-1 text-muted hover:text-foreground cursor-pointer" title="Reconnect">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => hostRef.current?.requestFullscreen?.()}
            className="rounded p-1 text-muted hover:text-foreground cursor-pointer" title="Fullscreen">
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
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
        </>
      )}
    </div>
  );
}
