import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { BookOpen, Bot, Database, FolderOpen, MessageSquare, Moon, Plus, Settings, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useSessions, newSessionId } from "@/hooks/useSessions";
import type { Bootstrap } from "@/lib/api";
import { cn } from "@/lib/utils";

type AppShellProps = {
  bootstrap: Bootstrap | null;
  dark: boolean;
  setDark: (dark: boolean) => void;
};

const nav = [
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/vault", label: "Vault", icon: FolderOpen },
  { to: "/wiki", label: "Wiki", icon: BookOpen },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ bootstrap, dark, setDark }: AppShellProps) {
  const sessions = useSessions();
  const navigate = useNavigate();

  function startNewChat() {
    navigate(`/chat?session=${newSessionId()}`);
  }

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r bg-background/95 px-3 py-4 lg:block">
        <Link to="/chat" className="flex h-10 items-center gap-2 px-2">
          <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Bot className="size-4" />
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">OH-MY-NEURO</div>
            <div className="truncate text-xs text-muted-foreground">Local RAG console</div>
          </div>
        </Link>

        <nav className="mt-6 space-y-1">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  "flex h-9 items-center gap-2 rounded-md px-2 text-sm transition-colors",
                  isActive ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary",
                )
              }
            >
              <item.icon className="size-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-7">
          <div className="flex items-center justify-between px-2">
            <div className="text-xs font-medium uppercase text-muted-foreground">최근 대화</div>
            <Button size="icon" variant="ghost" className="size-7" onClick={startNewChat}>
              <Plus className="size-4" />
            </Button>
          </div>
          <div className="mt-2 space-y-1">
            {sessions.sessions.slice(0, 8).map((session) => (
              <Link
                key={session.id}
                to={`/chat?session=${session.id}`}
                className="block truncate rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
              >
                {session.title}
              </Link>
            ))}
          </div>
        </div>

        <div className="absolute bottom-4 left-3 right-3 space-y-3">
          <div className="rounded-md border bg-secondary/40 p-3">
            <div className="flex items-center gap-2 text-xs font-medium">
              <Database className="size-3.5" />
              Vault
            </div>
            <div className="mt-1 truncate text-xs text-muted-foreground">
              {bootstrap?.vault_path || "미설정"}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <Badge variant={bootstrap?.api_key_configured ? "secondary" : "warning"}>
                {bootstrap?.api_key_configured ? "API key OK" : "API key 없음"}
              </Badge>
              <Badge variant="outline">{bootstrap?.indexed_files ?? 0} files</Badge>
              {bootstrap?.wiki?.page_count ? <Badge variant="outline">{bootstrap.wiki.page_count} wiki</Badge> : null}
            </div>
          </div>
          <Button variant="ghost" className="w-full justify-start" onClick={() => setDark(!dark)}>
            {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
            {dark ? "Light" : "Dark"}
          </Button>
        </div>
      </aside>

      <main className="lg:pl-64">
        <div className="mx-auto min-h-screen max-w-6xl px-4 py-4 sm:px-6 lg:px-8">
          <Outlet />
        </div>
      </main>

      <nav className="fixed bottom-0 left-0 right-0 z-20 flex border-t bg-background/95 p-2 backdrop-blur lg:hidden">
        {nav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                "flex flex-1 flex-col items-center gap-1 rounded-md py-2 text-[11px]",
                isActive ? "bg-secondary text-foreground" : "text-muted-foreground",
              )
            }
          >
            <item.icon className="size-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
