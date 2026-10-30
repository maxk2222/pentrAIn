/* Minimal shadcn-style UI primitives (self-contained, Tailwind v4). */
import * as React from "react";
import { cn } from "@/lib/utils";

export function Button({
  className, variant = "default", size = "default", ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "secondary" | "outline" | "ghost" | "danger" | "success";
  size?: "default" | "sm" | "lg" | "icon";
}) {
  const variants = {
    default: "bg-primary text-white hover:bg-primary-2",
    secondary: "bg-surface-2 text-foreground hover:bg-border border border-border",
    outline: "border border-border bg-transparent hover:bg-surface-2 text-foreground",
    ghost: "hover:bg-surface-2 text-muted hover:text-foreground",
    danger: "bg-danger/15 text-danger border border-danger/40 hover:bg-danger/25",
    success: "bg-success/15 text-success border border-success/40 hover:bg-success/25",
  };
  const sizes = {
    default: "h-9 px-4 text-sm",
    sm: "h-7 px-3 text-xs",
    lg: "h-11 px-6 text-base",
    icon: "h-9 w-9",
  };
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors",
        "disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
        variants[variant], sizes[size], className)}
      {...props}
    />
  );
}

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-xl border border-border bg-surface", className)} {...props} />;
}
export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1 p-4", className)} {...props} />;
}
export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("font-semibold leading-none", className)} {...props} />;
}
export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4 pt-0", className)} {...props} />;
}

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-9 w-full rounded-md border border-border bg-surface-2 px-3 text-sm",
        "placeholder:text-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
        className)}
      {...props}
    />
  );
}

export function Badge({ className, variant = "default", ...props }:
  React.HTMLAttributes<HTMLSpanElement> & { variant?: "default" | "outline" | "success" | "warning" | "danger" | "accent" }) {
  const variants = {
    default: "bg-surface-2 text-muted border-border",
    outline: "text-muted border-border",
    success: "bg-success/15 text-success border-success/40",
    warning: "bg-warning/15 text-warning border-warning/40",
    danger: "bg-danger/15 text-danger border-danger/40",
    accent: "bg-accent/15 text-accent border-accent/40",
  };
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
      variants[variant], className)} {...props} />
  );
}

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse rounded-md bg-surface-2", className)} {...props} />;
}

export function Progress({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-2", className)}>
      <div className="h-full bg-primary transition-all" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  );
}

export function Tabs({ tabs, active, onChange, className }: {
  tabs: { id: string; label: React.ReactNode }[];
  active: string; onChange: (id: string) => void; className?: string;
}) {
  return (
    <div className={cn("flex gap-1 rounded-lg bg-surface-2 p-1", className)}>
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={cn("flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors cursor-pointer",
            active === t.id ? "bg-surface text-foreground shadow" : "text-muted hover:text-foreground")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Select({ className, children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn("h-9 rounded-md border border-border bg-surface-2 px-3 text-sm text-foreground",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary cursor-pointer", className)}
      {...props}>{children}</select>
  );
}

export function Slider({ value, min, max, step = 1, onChange, className }: {
  value: number; min: number; max: number; step?: number;
  onChange: (v: number) => void; className?: string;
}) {
  return (
    <input type="range" value={value} min={min} max={max} step={step}
      onChange={(e) => onChange(Number(e.target.value))}
      className={cn("w-full accent-primary cursor-pointer", className)} />
  );
}

export function Switch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
      className={cn("relative h-5 w-9 rounded-full transition-colors cursor-pointer",
        checked ? "bg-primary" : "bg-border")}>
      <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform",
        checked ? "translate-x-4" : "translate-x-0.5")} />
    </button>
  );
}
