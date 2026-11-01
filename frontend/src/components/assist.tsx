/* Solve-style chips — which aids an attempt used (leaderboards, quest detail). */
import { BookOpen, Bot, Lightbulb, MessageSquare, Sparkles, Zap } from "lucide-react";
import type { Assistance } from "@/lib/api";
import { Badge } from "@/components/ui";

export const AID_CHIPS = [
  { key: "takeovers", icon: Zap, label: "takeover", title: "Elliot executed commands in Kali" },
  { key: "hints", icon: Lightbulb, label: "hint", title: "Paid hints revealed" },
  { key: "coach_msgs", icon: MessageSquare, label: "coach", title: "Messages sent to Elliot" },
  { key: "coach_nudges", icon: Sparkles, label: "tips", title: "Elliot-initiated hints/nudges" },
  { key: "sheet", icon: BookOpen, label: "sheet", title: "Reference sheet opened" },
  { key: "chat", icon: Bot, label: "panel", title: "Elliot panel opened" },
] as const;

export function AssistBadges({ attempt: a }: {
  attempt: { hints_used?: number; coach_interventions?: number; assistance?: Assistance };
}) {
  const as = a.assistance ?? {};
  const vals: Record<string, number> = {
    takeovers: as.takeovers ?? a.coach_interventions ?? 0,
    hints: as.hints ?? a.hints_used ?? 0,
    coach_msgs: as.coach_msgs ?? 0,
    coach_nudges: as.coach_nudges ?? 0,
    sheet: as.sheet ?? 0,
    chat: as.chat ?? 0,
  };
  if (!Object.values(vals).some(Boolean)) {
    return <Badge variant="success" title="Solved with no assistance">solo</Badge>;
  }
  return (
    <span className="flex flex-wrap items-center gap-1">
      {AID_CHIPS.map(({ key, icon: Icon, label, title }) =>
        vals[key] ? (
          <Badge key={key} variant="outline" title={title}
            className="gap-1 font-normal text-muted">
            <Icon className="h-3 w-3" />
            {label}{vals[key] > 1 ? ` ×${vals[key]}` : ""}
          </Badge>
        ) : null,
      )}
    </span>
  );
}
