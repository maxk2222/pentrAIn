import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrainCircuit, Gauge, Package, RefreshCw, Save, Server, Shield } from "lucide-react";
import { api, type EngineStatus, type Settings } from "@/lib/api";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Select, Slider, Switch } from "@/components/ui";

interface Spec {
  label: string; type: "text" | "int" | "float" | "bool" | "choice" | "password";
  min?: number; max?: number; step?: number; choices?: { value: string; label: string }[];
  placeholder?: string; help?: string;
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
      ["engine.ludus_url", { label: "Ludus API URL", type: "text", placeholder: "https://engine:8081" }],
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
      ["llm.model", { label: "Chat model", type: "text" }],
      ["llm.vision_model", { label: "Vision model (optional)", type: "text" }],
      ["llm.temperature", { label: "Temperature", type: "float", min: 0, max: 1.5, step: 0.05 }],
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
              <SettingField key={key} spec={spec} value={get(key)}
                onChange={(v) => setDraft((d) => ({ ...d, [key]: v }))} />
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function SettingField({ spec, value, onChange }: {
  spec: Spec; value: unknown; onChange: (v: unknown) => void;
}) {
  const label = <span className="mb-1.5 block text-sm font-medium text-muted">{spec.label}</span>;

  if (spec.type === "bool") {
    return (
      <div className="flex items-center justify-between rounded-lg border border-border p-3">
        <span className="text-sm font-medium text-muted">{spec.label}</span>
        <Switch checked={Boolean(value)} onChange={onChange} />
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
    </div>
  );
}
