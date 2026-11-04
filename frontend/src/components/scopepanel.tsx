/** Engagement scope (ROE) editor — locks the session onto an explicit
 * authorized whitelist. While locked the coach hard-denies every IP/host
 * outside it; unlocking restores LAN/range semantics. */
import { useEffect, useState } from "react";
import { ShieldCheck, ShieldOff, TriangleAlert } from "lucide-react";
import { api, type EngagementScope } from "@/lib/api";
import { Button, Card, CardContent, Input } from "@/components/ui";

function lines(s: string): string[] {
  return s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);
}

export function ScopePanel({ sessionId, scope, onClose, onChanged }: {
  sessionId: number;
  scope: EngagementScope | null | undefined;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [auth, setAuth] = useState("");
  const [nets, setNets] = useState("");
  const [hosts, setHosts] = useState("");
  const [urls, setUrls] = useState("");
  const [ports, setPorts] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function save() {
    setBusy(true); setErr(null);
    try {
      await api.post(`/api/sessions/${sessionId}/scope`, {
        authorization: auth,
        nets: lines(nets),
        hosts: lines(hosts),
        urls: lines(urls),
        ports: lines(ports).map(Number).filter((n) => Number.isInteger(n)),
      });
      onChanged();
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message.slice(0, 240) : "scope rejected");
    } finally {
      setBusy(false);
    }
  }

  async function unlock() {
    if (!confirm("Remove the engagement scope? The coach falls back to "
      + "LAN/range guard semantics.")) return;
    setBusy(true); setErr(null);
    try {
      await api.del(`/api/sessions/${sessionId}/scope`);
      onChanged();
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message.slice(0, 240) : "unlock failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4">
      <Card className="w-full max-w-lg border-border">
        <CardContent className="p-5">
          <div className="mb-3 flex items-center gap-2">
            {scope?.locked
              ? <ShieldCheck className="h-5 w-5 text-success" />
              : <ShieldOff className="h-5 w-5 text-muted" />}
            <span className="font-semibold">
              {scope?.locked ? "Engagement scope (locked)" : "Engagement scope"}
            </span>
          </div>

          {scope?.locked && (
            <div className="mb-4 space-y-1 rounded border border-border bg-surface p-3 text-xs">
              <div><span className="text-muted">nets: </span>
                <span className="font-mono">{scope.nets.join(", ") || "—"}</span></div>
              <div><span className="text-muted">hosts: </span>
                <span className="font-mono">{scope.hosts.join(", ") || "—"}</span></div>
              {scope.ports.length > 0 && (
                <div><span className="text-muted">ports: </span>
                  <span className="font-mono">{scope.ports.join(", ")}</span></div>)}
              <div><span className="text-muted">authorized: </span>
                <span>{scope.authorized_by}</span>
                <span className="text-muted"> at {scope.authorized_at}</span></div>
              {scope.unresolved?.length ? (
                <div className="text-warning">
                  unresolved hosts: {scope.unresolved.join(", ")}
                </div>) : null}
            </div>
          )}

          <p className="mb-3 text-xs leading-relaxed text-muted">
            {scope?.locked
              ? "Posting a new scope replaces this snapshot. The coach denies every "
                + "command against anything outside it — hard ROE boundary, not a prompt hint."
              : "No engagement scope set — the coach runs in LAN/range mode (targets "
                + "+ discovered hosts allowed). Lock it for external targets: every "
                + "IP/host outside the whitelist is then denied in code."}
          </p>

          <div className="space-y-2 text-xs">
            <label className="block">
              <span className="text-muted">Authorization (required) — who authorized this, reference:</span>
              <Input value={auth} onChange={(e) => setAuth(e.target.value)}
                placeholder="e.g. ACME contract #42, signed 2026-11-01, valid 30 days"
                className="mt-0.5 font-mono" />
            </label>
            <label className="block">
              <span className="text-muted">Nets — one CIDR or IP per line:</span>
              <textarea value={nets} onChange={(e) => setNets(e.target.value)}
                rows={3} placeholder={"203.0.113.0/29\n198.51.100.10/32"}
                className="mt-0.5 w-full rounded border border-border bg-surface p-2 font-mono text-xs" />
            </label>
            <label className="block">
              <span className="text-muted">Hosts — authorized domains (subdomains included):</span>
              <textarea value={hosts} onChange={(e) => setHosts(e.target.value)}
                rows={2} placeholder="app.example.com"
                className="mt-0.5 w-full rounded border border-border bg-surface p-2 font-mono text-xs" />
            </label>
            <label className="block">
              <span className="text-muted">URLs (optional) — contribute host + port to the whitelist:</span>
              <Input value={urls} onChange={(e) => setUrls(e.target.value)}
                placeholder="https://app.example.com:8443/portal"
                className="mt-0.5 font-mono" />
            </label>
            <label className="block">
              <span className="text-muted">Ports (optional ROE whitelist — empty = all):</span>
              <Input value={ports} onChange={(e) => setPorts(e.target.value)}
                placeholder="80, 443"
                className="mt-0.5 font-mono" />
            </label>
          </div>

          {err && (
            <div className="mt-3 flex items-start gap-2 rounded border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{err}</span>
            </div>)}

          <div className="mt-4 flex items-center gap-2">
            <Button variant="danger" size="sm" onClick={save}
              disabled={busy || auth.trim().length < 8}>
              Lock scope
            </Button>
            {scope?.locked && (
              <Button variant="secondary" size="sm" onClick={unlock}
                disabled={busy}>
                Remove scope
              </Button>)}
            <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
            <span className="ml-auto text-[10px] text-muted">
              applies on next coach attach — restart the session's coach to force
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
