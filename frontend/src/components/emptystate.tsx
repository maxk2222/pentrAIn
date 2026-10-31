/* Centered placeholder for empty lists/filters. */
import { cn } from "@/lib/utils";

export function EmptyState({ icon: Icon, title, hint, className }: {
  icon?: React.ElementType; title: string; hint?: string; className?: string;
}) {
  return (
    <div className={cn("py-10 text-center", className)}>
      {Icon && <Icon className="mx-auto mb-2 h-8 w-8 text-muted/50" />}
      <div className="text-sm text-muted">{title}</div>
      {hint && <div className="mt-1 text-xs text-muted/60">{hint}</div>}
    </div>
  );
}
