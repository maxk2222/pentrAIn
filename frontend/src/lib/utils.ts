import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtDuration(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** "flags 750 · +time 135 · −hints 40" — score tooltip. time_bonus shows
 * even at 0 (transparency: time always weighs in); costs only when they
 * actually hit the score. */
export function scoreTitle(b?: {
  flags?: number; time_bonus?: number; hint_cost?: number;
  takeover_penalty?: number;
}): string | undefined {
  if (!b || b.flags == null) return undefined;
  const parts = [`flags ${b.flags}`];
  if (b.time_bonus != null) parts.push(`+time ${b.time_bonus}`);
  if (b.hint_cost) parts.push(`−hints ${b.hint_cost}`);
  if (b.takeover_penalty) parts.push(`−takeover ${b.takeover_penalty}`);
  return parts.join(" · ");
}

export function fmtGb(n: number): string {
  return `${n} GB`;
}
