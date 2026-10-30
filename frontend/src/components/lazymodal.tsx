import { useEffect } from "react";
import { TriangleAlert } from "lucide-react";
import { Button, Card, CardContent } from "@/components/ui";

/** Warning shown when a trainee expands an assistance panel (sheet / coach).
 *  Honest framing: help is fine — just know what it costs. */
export function LazyModal({ what, onConfirm, onCancel }: {
  what: string; onConfirm: () => void; onCancel: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4">
      <Card className="w-full max-w-md border-warning/50">
        <CardContent className="p-5">
          <div className="mb-2 flex items-center gap-2 text-warning">
            <TriangleAlert className="h-5 w-5" />
            <span className="font-semibold">Assistance ahead</span>
          </div>
          <p className="text-sm leading-relaxed text-muted">
            Opening <span className="text-foreground font-medium">{what}</span> hands
            part of the thinking to the platform. Reference material and an AI coach
            are great for unblocking — and terrible for the skill you're here to build
            if you reach for them first.
          </p>
          <div className="mt-4 flex items-center gap-2">
            <Button variant="danger" onClick={onConfirm} autoFocus>
              Yes, I'm a lazy cunt.
            </Button>
            <Button variant="ghost" onClick={onCancel}>
              I'll do it myself.
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
