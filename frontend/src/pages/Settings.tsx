import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrainCircuit, Gauge, Package, PlugZap, RefreshCw, Save, Server, Shield } from "lucide-react";
import { api, type EngineResources, type EngineStatus, type LlmEffortsOut, type LlmModelsOut, type LlmTestOut, type Settings } from "@/lib/api";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Select, Slider, Switch } from "@/components/ui";

interface Spec {
  label: string; type: "text" | "int" | "float" | "bool" | "choice" | "password" | "model" | "effort";
  min?: number; max?: number; step?: number; choices?: { value: string; label: string }[];
  placeholder?: string; help?: string; kind?: "chat" | "vision";
}

/** UI metadata for the typed settings registry (backend services/settings.py DEFAULTS). */
const GROUPS: { title: string; icon: React.ElementType; keys: [string, Spec][] }[] = [
  {
    title: "Range engine", icon: Server,
    keys: [
      ["engine.pve_url", { label: "Proxmox API URL", type: "text", placeholder: "https://engine:8006" }],
      ["engine.pve_node", { label: "PVE node name", type: "text" }],
      ["engine.pve_token_id", { label: "API token ID", type: "text", placeholder: "root@pam!pentrain" }],
      ["engine.pve_token_secret", { label: "API token secret", type: "password" }],
      ["engine.ludus_url", { label: "Ludus API URL", type: "text", placeholder: "https://engine:8080" }],
      ["engine.ludus_api_key", { label: "Ludus API key", type: "password" }],
    ],
  },
  {
    title: "Resource budget — quests unlock when they fit", icon: Gauge,
    keys: [
      ["resources.max_ram_gb", { label: "Max RAM for ranges", type: "int", min: 8, max: 256, step: 4 }],
      ["resources.max_vcpus", { label: "Max vCPUs", type: "int", min: 2, max: 64 }],
      ["resources.max_disk_gb", { label: "Max disk", type: "int", min: 50, max: 4000, step: 50 }],
    ],
  },
  {
    title: "Coach LLM (OpenAI-compatible endpoint)", icon: BrainCircuit,
    keys: [
      ["llm.base_url", { label: "Base URL", type: "text", placeholder: "http://localhost:11434/v1" }],
      ["llm.api_key", { label: "API key", type: "password" }],
      ["llm.model", { label: "Chat model", type: "model", kind: "chat" }],
      ["llm.vision_model", { label: "Vision model (optional)", type: "model", kind: "vision" }],
      ["llm.temperature", { label: "Temperature", type: "float", min: 0, max: 1.5, step: 0.05 }],
      ["llm.reasoning", { label: "Thinking / reasoning", type: "bool", help: "Let reasoning-capable models think before answering (disable for fastest replies)" }],
      ["llm.reasoning_effort", {
        label: "Reasoning effort", type: "effort",
        help: "levels detected from the endpoint — 'none' ≈ reasoning off",
      }],
      ["llm.daily_token_budget", { label: "Daily token budget (0 = unlimited)", type: "int", min: 0, max: 100_000_000, step: 100000 }],
    ],
  },
  {
    title: "Coach behavior", icon: BrainCircuit,
    keys: [
      ["coach.enabled", { label: "Coach enabled", type: "bool" }],
      ["coach.default_autonomy", {
        label: "Default autonomy", type: "choice", choices: [
          { value: "1", label: "1 — Observer (hints only)" },
          { value: "2", label: "2 — Mentor (adaptive guidance)" },
          { value: "3", label: "3 — Copilot (suggests commands, you confirm)" },
          { value: "4", label: "4 — Autonomous (acts on Kali)" },
        ],
      }],
      ["coach.verbosity", {
        label: "Verbosity", type: "choice", choices: [
          { value: "terse", label: "Terse" }, { value: "normal", label: "Normal" },
          { value: "verbose", label: "Verbose" },
        ],
      }],
      ["coach.reflect_interval_s", { label: "Reflect interval (s)", type: "int", min: 15, max: 600, step: 15 }],
      ["coach.nudge_after_s", { label: "Nudge after idle (s)", type: "int", min: 60, max: 3600, step: 60 }],
      ["coach.hint_after_s", { label: "Hint after stuck (s)", type: "int", min: 120, max: 7200, step: 60 }],
      ["coach.action_budget", { label: "Coach action budget / session", type: "int", min: 0, max: 500, step: 10 }],
    ],
  },
  {
    title: "Data & retention", icon: Shield,
    keys: [
      ["data.telemetry_retention_days", { label: "Telemetry retention (days)", type: "int", min: 1, max: 365 }],
    ],
  },
];

export function SettingsPage() {
  const qc = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/api/settings") });
  const { data: engine } = useQuery({
    queryKey: ["engine-status"],
    queryFn: () => api.get<EngineStatus>("/api/engine/status"),
  });
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);
  const [detectMsg, setDetectMsg] = useState("");

  const save = useMutation({
    mutationFn: (updates: Record<string, unknown>) =>
      api.patch<Settings>("/api/settings", { updates }),
    onSuccess: () => {
      setDraft({}); setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["engine-status"] });
    },
  });

  const sync = useMutation({
    mutationFn: () => api.post("/api/packs/sync"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tracks"] });
      qc.invalidateQueries({ queryKey: ["quests"] });
    },
  });

  const detect = useMutation({
    mutationFn: () => api.get<EngineResources>("/api/engine/resources"),
    onSuccess: (r) => {
      if (r.ok && r.suggested) {
        setDraft((d) => ({
          ...d,
          "resources.max_ram_gb": r.suggested!.max_ram_gb,
          "resources.max_vcpus": r.suggested!.max_vcpus,
          "resources.max_disk_gb": r.suggested!.max_disk_gb,
        }));
        setDetectMsg(
          `host: ${r.ram_free_gb}G RAM free · ${r.cores} cores · ${r.disk_free_gb}G disk free ` +
          `→ suggested budget loaded (save to apply)`);
      } else {
        setDetectMsg(r.reason || "no engine data available");
      }
    },
    onError: (e) => setDetectMsg(e instanceof Error ? e.message : "detect failed"),
  });

  const get = (key: string) => (key in draft ? draft[key] : settings?.[key]);

  return (
    <div className="space-y-5 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Settings</h1>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => sync.mutate()} disabled={sync.isPending}>
            <Package className="h-4 w-4" /> {sync.isPending ? "Syncing…" : "Sync quest packs"}
          </Button>
          <Button onClick={() => save.mutate(draft)} disabled={!Object.keys(draft).length || save.isPending}>
            <Save className="h-4 w-4" /> {saved ? "Saved" : "Save changes"}
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <Server className="h-4 w-4 text-primary" /> Engine status
          </CardTitle>
          <Badge variant={engine?.health?.ok ? "success" : "danger"}>
            {engine?.mode ?? "?"} · {engine?.health?.ok ? "reachable" : "unreachable"}
          </Badge>
        </CardHeader>
        {engine && !engine.health?.ok && (
          <CardContent className="text-sm text-muted">
            Engine unreachable — falling back to the mock provider until credentials are configured.
            <Button variant="ghost" size="sm" className="ml-2"
              onClick={() => qc.invalidateQueries({ queryKey: ["engine-status"] })}>
              <RefreshCw className="h-3.5 w-3.5" /> recheck
            </Button>
          </CardContent>
        )}
      </Card>

      {GROUPS.map((g) => (
        <Card key={g.title}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <g.icon className="h-4 w-4 text-primary" /> {g.title}
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {g.keys.map(([key, spec]) => (
              <SettingField key={key} spec={spec} value={get(key)} get={get}
                onChange={(v) => setDraft((d) => ({ ...d, [key]: v }))} />
            ))}
            {g.title.startsWith("Resource budget") && (
              <div className="flex flex-wrap items-center gap-3 md:col-span-2">
                <Button variant="secondary" size="sm" onClick={() => detect.mutate()}
                  disabled={detect.isPending}>
                  <Gauge className="h-4 w-4" />
                  {detect.isPending ? "Reading host…" : "Auto-detect from engine host"}
                </Button>
                {detectMsg && <span className="text-xs text-muted">{detectMsg}</span>}
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function SettingField({ spec, value, onChange, get }: {
  spec: Spec; value: unknown; onChange: (v: unknown) => void;
  get: (k: string) => unknown;
}) {
  const label = <span className="mb-1.5 block text-sm font-medium text-muted">{spec.label}</span>;
  const help = spec.help ? <span className="mt-1 block text-xs text-muted/70">{spec.help}</span> : null;

  if (spec.type === "model") {
    return <ModelField spec={spec} value={value} onChange={onChange} get={get} />;
  }
  if (spec.type === "effort") {
    return <EffortField spec={spec} value={value} onChange={onChange} get={get} />;
  }
  if (spec.type === "bool") {
    return (
      <div className="rounded-lg border border-border p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-muted">{spec.label}</span>
          <Switch checked={Boolean(value)} onChange={onChange} />
        </div>
        {help}
      </div>
    );
  }
  if (spec.type === "choice" && spec.choices) {
    return (
      <div>{label}
        <Select className="w-full" value={String(value ?? "")}
          onChange={(e) => onChange(/^\d+$/.test(e.target.value) ? Number(e.target.value) : e.target.value)}>
          {spec.choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </Select>
      </div>
    );
  }
  if ((spec.type === "int" || spec.type === "float") && spec.min != null && spec.max != null) {
    return (
      <div>{label}
        <div className="flex items-center gap-3">
          <Slider min={spec.min} max={spec.max} step={spec.step ?? 1}
            value={Number(value ?? spec.min)} onChange={onChange} />
          <span className="w-16 text-right text-sm font-medium">{String(value)}</span>
        </div>
      </div>
    );
  }
  return (
    <div>{label}
      <Input
        type={spec.type === "password" ? "password" : "text"}
        value={String(value ?? "")}
        placeholder={spec.placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      {help}
    </div>
  );
}

/** Model picker: dropdown fed by the endpoint's /models listing, free-text
 *  fallback for endpoints that don't expose it, and a live inference test. */
function ModelField({ spec, value, onChange, get }: {
  spec: Spec; value: unknown; onChange: (v: unknown) => void;
  get: (k: string) => unknown;
}) {
  const model = String(value ?? "");
  const baseUrl = String(get("llm.base_url") ?? "");
  const apiKey = String(get("llm.api_key") ?? "");
  const [models, setModels] = useState<string[] | null>(null);
  const [listMsg, setListMsg] = useState("");
  const [fetching, setFetching] = useState(false);
  const [test, setTest] = useState<{ ok?: boolean; text: string } | null>(null);
  const [custom, setCustom] = useState(false);

  const fetchModels = useCallback(async () => {
    setFetching(true); setListMsg("");
    try {
      const r = await api.post<LlmModelsOut>("/api/llm/models",
        { base_url: baseUrl, api_key: apiKey });
      if (r.ok) {
        setModels(r.models.map((m) => m.id));
        if (!r.models.length) setListMsg("endpoint lists no models — enter one manually");
      } else {
        setModels(null);
        setListMsg(r.error || "model list failed — enter one manually");
      }
    } catch (e) {
      setModels(null);
      setListMsg(e instanceof Error ? e.message : "failed");
    } finally {
      setFetching(false);
    }
  }, [baseUrl, apiKey]);

  // pull the endpoint's model catalog automatically — debounced so typing a
  // new base_url doesn't fire a request per keystroke
  useEffect(() => {
    if (!baseUrl) { setModels(null); return; }
    const t = setTimeout(fetchModels, 600);
    return () => clearTimeout(t);
  }, [baseUrl, fetchModels]);

  const runTest = async () => {
    setTest({ text: "testing…" });
    try {
      const r = await api.post<LlmTestOut>("/api/llm/test", {
        model, kind: spec.kind ?? "chat", base_url: baseUrl, api_key: apiKey,
      });
      setTest(r.ok
        ? { ok: true, text: `ok · ${r.latency_ms}ms${r.sample ? ` — “${r.sample}”` : ""}` }
        : { ok: false, text: r.error || "test failed" });
    } catch (e) {
      setTest({ ok: false, text: e instanceof Error ? e.message : "test failed" });
    }
  };

  const opts = models ? [...models] : [];
  if (model && !opts.includes(model)) opts.unshift(model);  // saved value always selectable
  const showCustom = custom || (!model && !opts.length);

  return (
    <div>
      <span className="mb-1.5 block text-sm font-medium text-muted">{spec.label}</span>
      <div className="flex gap-2">
        <Select className="min-w-0 flex-1" value={showCustom ? "__custom__" : model}
          onChange={(e) => {
            if (e.target.value === "__custom__") setCustom(true);
            else { setCustom(false); onChange(e.target.value); }
          }}>
          {!model && !showCustom && <option value="">select…</option>}
          {opts.map((m) => <option key={m} value={m}>{m}</option>)}
          <option value="__custom__">custom…</option>
        </Select>
        <Button variant="secondary" size="sm" title="Fetch model list from endpoint"
          onClick={fetchModels} disabled={fetching || !baseUrl}>
          <RefreshCw className={`h-4 w-4 ${fetching ? "animate-spin" : ""}`} />
        </Button>
        <Button variant="secondary" size="sm" title="Run a real inference request"
          onClick={runTest} disabled={!model || test?.text === "testing…" || !baseUrl}>
          <PlugZap className="h-4 w-4" /> Test
        </Button>
      </div>
      {showCustom && (
        <Input className="mt-2" value={model} placeholder="model id, e.g. qwen3:30b"
          onChange={(e) => onChange(e.target.value)} />
      )}
      {(listMsg || test) && (
        <div className="mt-1.5 space-y-0.5">
          {listMsg && <div className="text-xs text-warning">{listMsg}</div>}
          {test && (
            <div className={`text-xs ${test.ok === false ? "text-danger" : test.ok ? "text-success" : "text-muted"}`}>
              {test.text}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Reasoning-effort picker: probes the endpoint's real supported values
 *  (sends an invalid effort, parses "Supported values: …" from the error),
 *  falls back to the union list. */
function EffortField({ spec, value, onChange, get }: {
  spec: Spec; value: unknown; onChange: (v: unknown) => void;
  get: (k: string) => unknown;
}) {
  const effort = String(value ?? "");
  const baseUrl = String(get("llm.base_url") ?? "");
  const apiKey = String(get("llm.api_key") ?? "");
  const model = String(get("llm.model") ?? "");
  const reasoningOn = Boolean(get("llm.reasoning"));
  const [efforts, setEfforts] = useState<string[] | null>(null);
  const [source, setSource] = useState("");
  const [fetching, setFetching] = useState(false);

  const fetchEfforts = useCallback(async () => {
    setFetching(true);
    try {
      const r = await api.post<LlmEffortsOut>("/api/llm/reasoning-efforts",
        { base_url: baseUrl, api_key: apiKey, model });
      setEfforts(r.efforts);
      setSource(r.ok ? (r.source === "endpoint" ? "endpoint" : "defaults")
                     : `probe failed — ${r.error || "?"}`);
    } catch {
      setEfforts(null);
      setSource("probe failed");
    } finally {
      setFetching(false);
    }
  }, [baseUrl, apiKey, model]);

  useEffect(() => {
    if (!baseUrl || !model) { setEfforts(null); return; }
    const t = setTimeout(fetchEfforts, 600);
    return () => clearTimeout(t);
  }, [baseUrl, model, fetchEfforts]);

  const opts = efforts ? [...efforts] : [];
  if (effort && !opts.includes(effort)) opts.unshift(effort);

  return (
    <div>
      <span className="mb-1.5 block text-sm font-medium text-muted">{spec.label}</span>
      <div className="flex items-center gap-2">
        <Select className="w-full" value={effort} disabled={!reasoningOn}
          onChange={(e) => onChange(e.target.value)}>
          {!opts.includes(effort) && <option value={effort}>{effort || "…"}</option>}
          {opts.map((o) => <option key={o} value={o}>{o}</option>)}
        </Select>
        <Button variant="ghost" size="sm" onClick={fetchEfforts}
          disabled={fetching || !baseUrl || !model}>
          <RefreshCw className={`h-3.5 w-3.5 ${fetching ? "animate-spin" : ""}`} />
        </Button>
      </div>
      <span className="mt-1 block text-xs text-muted/70">
        {!reasoningOn ? "enable reasoning above to pick an effort" :
         source ? `· ${source}` : spec.help}
      </span>
    </div>
  );
}
