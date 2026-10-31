/* Minimal shadcn-style UI primitives (self-contained, Tailwind v4). */
import * as React from "react";
import { ChevronDown } from "lucide-react";
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

export function IconButton({ icon: Icon, label, active, badgeDot, variant = "ghost",
  size = "default", onClick, disabled, className }: {
  icon: React.ElementType; label: string; active?: boolean; badgeDot?: boolean;
  variant?: "ghost" | "danger"; size?: "sm" | "default";
  onClick?: () => void; disabled?: boolean; className?: string;
}) {
  return (
    <button onClick={onClick} disabled={disabled} title={label} aria-label={label}
      className={cn(
        "relative inline-flex items-center justify-center rounded-md transition-colors cursor-pointer",
        "focus-visible:ring-1 ring-primary disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-7 w-7" : "h-9 w-9",
        variant === "danger" ? "text-danger hover:bg-danger/15"
          : active ? "bg-primary/10 text-primary"
          : "text-muted hover:bg-surface-2 hover:text-foreground",
        className)}>
      <Icon className={size === "sm" ? "h-4 w-4" : "h-5 w-5"} />
      {badgeDot && <span className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-accent" />}
    </button>
  );
}

export function Tabs({ tabs, active, onChange, className }: {
  tabs: { id: string; label: React.ReactNode }[];
  active: string; onChange: (id: string) => void; className?: string;
}) {
  return (
    // overflow-x-auto + shrink-0: many tabs scroll instead of squeezing
    <div className={cn("flex gap-1 overflow-x-auto rounded-lg bg-surface-2 p-1", className)}>
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={cn("shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors cursor-pointer",
            active === t.id ? "bg-surface text-foreground shadow" : "text-muted hover:text-foreground")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Select({ className, children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  // className lands on the wrapper — callers pass layout classes (w-full, flex-1)
  return (
    <div className={cn("relative", className)}>
      <select
        className={cn("h-9 w-full appearance-none rounded-md border border-border bg-surface-2 px-3 pr-8 text-sm text-foreground",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary cursor-pointer",
          "disabled:cursor-not-allowed disabled:opacity-50")}
        {...props}>{children}</select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
    </div>
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

export function Switch({ checked, onChange, disabled, className }: {
  checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; className?: string;
}) {
  return (
    <button role="switch" aria-checked={checked} disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn("relative h-6 w-11 shrink-0 rounded-full transition-colors cursor-pointer",
        "focus-visible:outline-none focus-visible:ring-2 ring-primary/60 ring-offset-2 ring-offset-surface",
        checked ? "bg-primary" : "border border-border bg-surface-2",
        "disabled:cursor-not-allowed disabled:opacity-50", className)}>
      <span className={cn("absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform",
        checked ? "translate-x-[22px]" : "translate-x-0")} />
    </button>
  );
}
