import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { SearchX } from "lucide-react";
import { api, type Quest, type Track } from "@/lib/api";
import { Badge, Input, Tabs } from "@/components/ui";
import { EmptyState } from "@/components/emptystate";
import { TrackSection } from "@/components/questtree";

const STATUS_TABS = ["all", "open", "solved", "locked"] as const;

export function LibraryPage() {
  const [params, setParams] = useSearchParams();
  const track = params.get("track") ?? "";
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>("all");
  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: () => api.get<Track[]>("/api/tracks") });
  const { data: quests } = useQuery({ queryKey: ["quests"], queryFn: () => api.get<Quest[]>("/api/quests") });

  // filters dim nodes rather than removing them — the tree shape stays visible
  const dim = (q: Quest): boolean => {
    const needle = search.trim().toLowerCase();
    if (needle && !`${q.title} ${q.summary}`.toLowerCase().includes(needle)) return true;
    if (status === "open" && (q.locked || q.solved)) return true;
    if (status === "solved" && !q.solved) return true;
    if (status === "locked" && !q.locked) return true;
    return false;
  };

  const shownTracks = (tracks ?? []).filter((t) => !track || t.slug === track);
  const trackQuests = (slug: string) => (quests ?? []).filter((q) => q.track_slug === slug);
  const visible = shownTracks.flatMap((t) => trackQuests(t.slug));
  const allDimmed = visible.length > 0 && visible.every(dim);

  return (
    <div className="space-y-5 p-6">
      <h1 className="text-2xl font-bold">Quest Library</h1>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          tabs={[{ id: "", label: "All" }, ...(tracks ?? []).map((t) => ({ id: t.slug, label: t.title }))]}
          active={track}
          onChange={(id) => setParams(id ? { track: id } : {})}
        />
        <div className="flex items-center gap-2">
          <Input className="w-56" placeholder="Search quests…" value={search}
            onChange={(e) => setSearch(e.target.value)} />
          <Tabs tabs={STATUS_TABS.map((s) => ({ id: s, label: s }))}
            active={status} onChange={setStatus} />
        </div>
      </div>

      {shownTracks.map((t) => (
        <TrackSection key={t.slug} track={t} quests={trackQuests(t.slug)} dim={dim} />
      ))}
      {!visible.length && (
        <EmptyState icon={SearchX} title="No quests in this selection" />
      )}
      {allDimmed && (
        <EmptyState icon={SearchX} title="No quests match"
          hint="Clear the search or status filter to see them again." />
      )}
    </div>
  );
}

export function DifficultyBadge({ tier }: { tier: number }) {
  const v = tier <= 1 ? "success" : tier === 2 ? "warning" : "danger";
  return <Badge variant={v}>tier {tier}</Badge>;
}
