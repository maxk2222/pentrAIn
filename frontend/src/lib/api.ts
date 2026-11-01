/* API client — bearer token in localStorage, relative URLs (vite dev proxy / prod same-origin). */

const TOKEN_KEY = "pentrain_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method, headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    setToken(null);
    if (!location.pathname.startsWith("/login")) location.href = "/login";
    throw new Error("unauthorized");
  }
  if (res.status === 428) {
    location.href = "/setup";
    throw new Error("setup required");
  }
  if (!res.ok) {
    const text = await res.text();
    let detail: unknown = text;
    try { detail = JSON.parse(text).detail ?? text; } catch { /* keep raw */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => req<T>("GET", path),
  post: <T>(path: string, body?: unknown) => req<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => req<T>("PATCH", path, body),
};

/** WebSocket URL for a same-origin backend path, with auth token as query param. */
export function wsUrl(path: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const sep = path.includes("?") ? "&" : "?";
  return `${proto}//${location.host}${path}${sep}token=${encodeURIComponent(getToken() ?? "")}`;
}

/* ---------- types (mirror backend/app/schemas.py) ---------- */

export interface Track {
  slug: string; title: string; description: string; icon: string; order: number;
  quest_count: number; solved_count: number; level: number;
}

export interface Quest {
  id: string; track_slug: string; tier: number; title: string; summary: string;
  requirements: Record<string, number>;
  scoring: { par_s?: number; time_bonus_max?: number; takeover_cost?: number };
  locked: boolean; lock_reason: string; solved: boolean; best_score: number | null;
  exam: boolean;
}

export interface FlagDef {
  key: string; name: string; kind: string; points: number; solved: boolean;
}

export interface QuestDetail extends Quest {
  briefing_md: string; defense_md: string; topology: Topology;
  cheatsheet_md: string; track_cheatsheet_md: string;
  hints: { id: string; cost: number; stage: string }[];
  flags: FlagDef[];
}

export interface Topology {
  kali?: { template?: string; ram_gb?: number; cpus?: number };
  vms?: TopologyVm[];
}
export interface TopologyVm {
  name: string; template: string; vlan?: number; ip_last_octet?: number;
  ram_gb?: number; cpus?: number; linux?: boolean; windows?: unknown;
  domain?: string | Record<string, unknown>; roles?: string[];
}

export type SessionState =
  | "queued" | "deploying" | "ready" | "active" | "resetting"
  | "solved" | "aborting" | "aborted" | "failed";

export interface Session {
  id: number; quest_id: string; state: SessionState; kali_vmid: number | null;
  autonomy_level: number; coach_enabled: boolean; kali_internet?: boolean;
  kali_wan_ip?: string | null; subagents_enabled?: boolean;
  created_at: string | null; ready_at: string | null; error: string | null;
}

export interface FlagSubmitOut {
  correct: boolean; flag_key: string | null; points: number;
  all_solved: boolean; solved: string[]; total: number;
}

export interface SessionFlags {
  flags: FlagDef[]; solved: number; total: number;
}

/** Solve-style counters on an attempt — which aids the trainee used. */
export interface Assistance {
  hints?: number; coach_msgs?: number; coach_nudges?: number;
  takeovers?: number; sheet?: number; chat?: number;
}

/** Score decomposition persisted on the attempt — how time weighed in. */
export interface ScoreBreakdown {
  flags?: number; time_bonus?: number; hint_cost?: number;
  takeover_penalty?: number; par_s?: number;
}

export interface Attempt {
  id: number; quest_id: string; session_id: number; score: number;
  flags_found: number; flags_total: number; hints_used: number;
  coach_interventions: number; assistance?: Assistance;
  breakdown?: ScoreBreakdown;
  duration_s: number; created_at: string | null;
}

export interface QuestLeaderboard { best: Attempt | null; history: Attempt[] }
export interface GlobalBoardRow {
  quest_id: string; best_score: number; attempts: number; assistance?: Assistance;
  duration_s?: number | null; breakdown?: ScoreBreakdown;
}

export interface ChatMessage {
  id: number; role: "user" | "coach" | "system"; kind: string;
  content: string; meta?: Record<string, unknown>; ts: string | null;
}

export interface TelemetryEvent {
  id: number; kind: string; payload: Record<string, unknown>; ts: string | null;
}

export interface EngineStatus {
  mode: string; health: Record<string, unknown>; resources: Record<string, number>;
  node: Record<string, unknown> | null;
  vms?: { running: number; total: number } | null;
}

export interface EngineResources {
  ok: boolean; reason?: string;
  ram_total_gb?: number; ram_free_gb?: number; cores?: number; disk_free_gb?: number;
  suggested?: { max_ram_gb: number; max_vcpus: number; max_disk_gb: number };
}

export interface LlmModelsOut { ok: boolean; models: { id: string }[]; error?: string }
export interface LlmTestOut { ok: boolean; latency_ms?: number; error?: string; sample?: string }

export interface Profile {
  xp_total: number; track_levels: Record<string, number>;
  prefs: Record<string, unknown>; metrics: Record<string, unknown>;
}

export type Settings = Record<string, unknown>;

/** Event envelope pushed over /ws/session/{id}. */
export interface WsEvent {
  type: "state" | "deploy_log" | "flag" | "hint" | "solved" | "checkpoint"
       | "coach_message" | "coach_action" | "coach_stream" | "coach_activity"
       | "coach_agents" | "telemetry" | string;
  session_id?: number;
  data?: Record<string, any>;
  ts?: number;
}

export interface LlmEffortsOut {
  ok: boolean; efforts: string[]; source?: "endpoint" | "fallback"; error?: string;
}
export interface RrdRow {
  time: number; cpu?: number; maxcpu?: number; loadavg?: number;
  memused?: number; memtotal?: number; memavailable?: number;
  netin?: number; netout?: number; iowait?: number;
  roottotal?: number; rootused?: number; swapused?: number;
}
export interface EngineMetrics { ok: boolean; timeframe?: string; rows: RrdRow[]; reason?: string }
export interface SessionVmMetric {
  name: string; role: string; vmid: number; status?: string;
  cpu?: number; mem?: number; maxmem?: number; balloon?: number;
  netin?: number; netout?: number; uptime?: number; error?: string;
}
export interface SessionMetrics { ok: boolean; vms: SessionVmMetric[]; reason?: string }
export interface LlmUsageDay {
  day: string; requests: number; tokens: number;
  prompt: number; completion: number; avg_latency_ms: number;
}
export interface LlmUsageOut {
  days: LlmUsageDay[]; budget: number;
  by_model?: { model: string; requests: number; tokens: number }[];
  by_kind?: { kind: string; model: string; requests: number; tokens: number; avg_latency_ms: number }[];
}

export interface StoragePool {
  storage: string; type?: string; content?: string;
  total?: number; used?: number; avail?: number; active?: number; shared?: number;
  trend?: { time: number; used?: number; total?: number }[]; trend_error?: string;
}
export interface StorageOut { ok: boolean; reason?: string; pools: StoragePool[] }

export interface DiskInfo {
  dev?: string; model?: string; serial?: string; size_gb?: number; type?: string;
  health?: string; smart_health?: string; temp_c?: number; wearout_pct?: number;
  power_on_hours?: number; reallocated?: number; smart_error?: string;
}
export interface DisksOut { ok: boolean; reason?: string; disks: DiskInfo[] }

export interface HostStats {
  ok: boolean; reason?: string; url?: string; ts?: number;
  cpu?: { package_c?: number | null; temps: { label: string; c: number }[] };
  gpu?: { name: string; vendor: string; util_pct?: number | null;
          temp_c?: number | null; mem_used_mb?: number | null;
          mem_total_mb?: number | null } | null;
  fans?: { label: string; rpm: number }[];
}

export interface ActivityStats {
  ok: boolean;
  deploys: { sessions: number; ready: number; failed: number; avg_s: number; last_s: number };
  attempts: { day: string; count: number; avg_score: number }[];
  scores: { quest_id: string; score: number; ts: string }[];
  aids: Record<string, number>;
}

export interface VmHistoryRow {
  time: number; cpu?: number; maxcpu?: number;
  memused?: number; maxmem?: number; netin?: number; netout?: number;
}
export interface SessionVmHistory {
  name: string; role: string; vmid: number; rows?: VmHistoryRow[]; error?: string;
}
export interface SessionMetricsHistory {
  ok: boolean; timeframe?: string; reason?: string; vms: SessionVmHistory[];
}
