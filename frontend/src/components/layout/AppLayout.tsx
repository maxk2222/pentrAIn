import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Activity, FlaskConical, LayoutDashboard, Library, LogOut, Settings,
  Terminal, Trophy,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { setToken } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { useEffect } from "react";
import { Badge } from "@/components/ui";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/library", label: "Quest Library", icon: Library },
  { to: "/free", label: "Free Lab", icon: FlaskConical },
  { to: "/leaderboard", label: "Leaderboard", icon: Trophy },
  { to: "/stats", label: "Stats", icon: Activity },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function AppLayout() {
  const nav = useNavigate();
  const { activeSession, loadActiveSession } = useAppStore();

  useEffect(() => {
    loadActiveSession();
    const t = setInterval(loadActiveSession, 15000);
    return () => clearInterval(t);
  }, [loadActiveSession]);

  return (
    <div className="flex h-full">
      <aside className="flex w-60 flex-col border-r border-border bg-surface">
        <Link to="/" className="flex items-center gap-2.5 px-5 py-5">
          <img src="/logo-icon.png" alt="pentrAIn" className="h-7 w-auto" />
          <span className="text-lg font-bold tracking-tight">
            pentr<span className="text-primary">AI</span>n
          </span>
        </Link>

        {activeSession && (
          <Link to={`/session/${activeSession.id}`}
            className="mx-3 mb-3 flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/10 px-3 py-2 text-sm">
            <Terminal className="h-4 w-4 text-primary" />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{activeSession.quest_id}</div>
              <div className="text-xs text-muted capitalize">{activeSession.state}</div>
            </div>
            <Badge variant={activeSession.state === "active" ? "success" : "warning"}>
              {activeSession.state}
            </Badge>
          </Link>
        )}

        <nav className="flex-1 space-y-1 px-3">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}
              className={({ isActive }) => cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive ? "bg-surface-2 text-foreground" : "text-muted hover:bg-surface-2/60 hover:text-foreground")}>
              <n.icon className="h-4 w-4" />
              {n.label}
            </NavLink>
          ))}
        </nav>

        <button
          onClick={() => { setToken(null); nav("/login"); }}
          className="m-3 flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted hover:bg-surface-2/60 hover:text-foreground cursor-pointer">
          <LogOut className="h-4 w-4" /> Sign out
        </button>
      </aside>

      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
