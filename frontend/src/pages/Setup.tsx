import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Server, BrainCircuit, Gauge, KeyRound } from "lucide-react";
import { api, setToken } from "@/lib/api";
import { Button, Card, CardContent, CardHeader, CardTitle, Input, Select, Slider } from "@/components/ui";
import { cn } from "@/lib/utils";

const STEPS = [
  { id: "engine", label: "Engine", icon: Server },
  { id: "llm", label: "LLM", icon: BrainCircuit },
  { id: "resources", label: "Resources", icon: Gauge },
  { id: "admin", label: "Admin", icon: KeyRound },
] as const;

export function SetupPage() {
  const nav = useNavigate();
  const { data: status } = useQuery({
    queryKey: ["setup-status"],
    queryFn: () => api.get<{ completed: boolean; engine_mode: string }>("/api/setup/status"),
  });
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({
    "engine.pve_url": "", "engine.pve_node": "pve",
    "engine.pve_token_id": "", "engine.pve_token_secret": "",
    "engine.ludus_url": "", "engine.ludus_api_key": "",
    "llm.base_url": "http://localhost:11434/v1", "llm.api_key": "",
    "llm.model": "huihui-ai/Qwen3-30B-A3B-abliterated", "llm.vision_model": "",
    "llm.daily_token_budget": 2000000,
    "resources.max_ram_gb": 48, "resources.max_vcpus": 16, "resources.max_disk_gb": 500,
    admin_password: "", admin_password2: "",
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const mode = (status?.engine_mode ?? "nested") as string;
  const set = (k: keyof typeof form) => (v: string | number) =>
    setForm((f) => ({ ...f, [k]: v }));

  async function finish() {
    if (form.admin_password.length < 6) { setErr("password ≥ 6 chars"); return; }
    if (form.admin_password !== form.admin_password2) { setErr("passwords don't match"); return; }
    setBusy(true); setErr("");
    try {
      const { admin_password2: _ignore, ...updates } = form;
      const r = await api.post<{ ok: boolean; token: string }>("/api/setup/complete", { updates });
      setToken(r.token);
      await api.post("/api/packs/sync");
      nav("/");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "setup failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-full bg-background p-6">
      <div className="mx-auto max-w-2xl">
        <div className="mb-8 flex items-center gap-3">
          <img src="/logo-icon.png" alt="pentrAIn" className="h-10 w-auto" />
          <div>
            <h1 className="text-2xl font-bold">
              pentr<span className="text-primary">AI</span>n Setup
            </h1>
            <p className="text-sm text-muted">One-time platform configuration</p>
          </div>
        </div>

        <div className="mb-6 flex gap-2">
          {STEPS.map((s, i) => (
            <div key={s.id} className={cn(
              "flex flex-1 items-center gap-2 rounded-lg border px-3 py-2 text-sm",
              i === step ? "border-primary bg-primary/10 text-foreground"
                : i < step ? "border-success/40 text-success" : "border-border text-muted")}>
              {i < step ? <CheckCircle2 className="h-4 w-4" /> : <s.icon className="h-4 w-4" />}
              {s.label}
            </div>
          ))}
        </div>

        <Card>
          <CardHeader><CardTitle>{STEPS[step].label}</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {step === 0 && (
              <>
                <p className="text-sm text-muted">
                  Engine mode: <b className="text-foreground">{mode}</b>
                  {mode === "nested"
                    ? " — endpoints point at the nested engine VM installed by the installer."
                    : " — endpoints point at your dedicated Proxmox host."}
                </p>
                <Field label="Proxmox API URL"><Input placeholder="https://engine:8006" value={form["engine.pve_url"]} onChange={(e) => set("engine.pve_url")(e.target.value)} /></Field>
                <Field label="PVE node name"><Input value={form["engine.pve_node"]} onChange={(e) => set("engine.pve_node")(e.target.value)} /></Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="API token ID"><Input placeholder="root@pam!pentrain" value={form["engine.pve_token_id"]} onChange={(e) => set("engine.pve_token_id")(e.target.value)} /></Field>
                  <Field label="API token secret"><Input type="password" value={form["engine.pve_token_secret"]} onChange={(e) => set("engine.pve_token_secret")(e.target.value)} /></Field>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Ludus API URL"><Input placeholder="https://engine:8081" value={form["engine.ludus_url"]} onChange={(e) => set("engine.ludus_url")(e.target.value)} /></Field>
                  <Field label="Ludus API key"><Input type="password" value={form["engine.ludus_api_key"]} onChange={(e) => set("engine.ludus_api_key")(e.target.value)} /></Field>
                </div>
              </>
            )}
            {step === 1 && (
              <>
                <p className="text-sm text-muted">Any OpenAI-compatible endpoint (Ollama /v1, vLLM, LM Studio, gateway). An abliterated model is recommended for coaching depth — it runs on your infrastructure.</p>
                <Field label="Base URL"><Input value={form["llm.base_url"]} onChange={(e) => set("llm.base_url")(e.target.value)} /></Field>
                <Field label="API key (optional)"><Input type="password" value={form["llm.api_key"]} onChange={(e) => set("llm.api_key")(e.target.value)} /></Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Model"><Input value={form["llm.model"]} onChange={(e) => set("llm.model")(e.target.value)} /></Field>
                  <Field label="Vision model (optional)"><Input value={form["llm.vision_model"]} onChange={(e) => set("llm.vision_model")(e.target.value)} /></Field>
                </div>
              </>
            )}
            {step === 2 && (
              <>
                <p className="text-sm text-muted">Quests unlock when their requirements fit inside this budget. Adjust anytime in Settings.</p>
                <Field label={`Max RAM for ranges: ${form["resources.max_ram_gb"]} GB`}>
                  <Slider min={8} max={256} step={4} value={form["resources.max_ram_gb"]} onChange={set("resources.max_ram_gb")} />
                </Field>
                <Field label={`Max vCPUs: ${form["resources.max_vcpus"]}`}>
                  <Slider min={2} max={64} value={form["resources.max_vcpus"]} onChange={set("resources.max_vcpus")} />
                </Field>
                <Field label={`Max disk: ${form["resources.max_disk_gb"]} GB`}>
                  <Slider min={50} max={4000} step={50} value={form["resources.max_disk_gb"]} onChange={set("resources.max_disk_gb")} />
                </Field>
              </>
            )}
            {step === 3 && (
              <>
                <Field label="Admin password"><Input type="password" value={form.admin_password} onChange={(e) => set("admin_password")(e.target.value)} /></Field>
                <Field label="Repeat password"><Input type="password" value={form.admin_password2} onChange={(e) => set("admin_password2")(e.target.value)} /></Field>
              </>
            )}
            {err && <p className="text-sm text-danger">{err}</p>}
            <div className="flex justify-between pt-2">
              <Button variant="secondary" disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
              {step < STEPS.length - 1
                ? <Button onClick={() => setStep(step + 1)}>Next</Button>
                : <Button variant="success" disabled={busy} onClick={finish}>{busy ? "Finishing…" : "Finish setup"}</Button>}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium text-muted">{label}</span>
      {children}
    </label>
  );
}
