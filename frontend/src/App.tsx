import { Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, getToken } from "@/lib/api";
import { AppLayout } from "@/components/layout/AppLayout";
import { LoginPage } from "@/pages/Login";
import { SetupPage } from "@/pages/Setup";
import { DashboardPage } from "@/pages/Dashboard";
import { LibraryPage } from "@/pages/Library";
import { QuestDetailPage } from "@/pages/QuestDetail";
import { SessionPage } from "@/pages/Session";
import { FreeLabPage } from "@/pages/FreeLab";
import { BuilderPage } from "@/pages/Builder";
import { LeaderboardPage } from "@/pages/Leaderboard";
import { StatsPage } from "@/pages/Stats";
import { SettingsPage } from "@/pages/Settings";

function Guard({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useQuery({
    queryKey: ["setup-status"],
    queryFn: () => api.get<{ completed: boolean }>("/api/setup/status"),
    retry: false,
  });
  if (isLoading) return <div className="grid h-full place-items-center text-muted">Loading…</div>;
  if (data && !data.completed) return <Navigate to="/setup" replace />;
  if (!getToken()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/setup" element={<SetupPage />} />
      <Route element={<Guard><AppLayout /></Guard>}>
        <Route index element={<DashboardPage />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/quests/:questId" element={<QuestDetailPage />} />
        <Route path="/session/:sessionId" element={<SessionPage />} />
        <Route path="/free" element={<FreeLabPage />} />
        <Route path="/builder" element={<BuilderPage />} />
        <Route path="/builder/:id" element={<BuilderPage />} />
        <Route path="/leaderboard" element={<LeaderboardPage />} />
        <Route path="/stats" element={<StatsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
