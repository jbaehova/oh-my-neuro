import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { useTheme } from "@/hooks/useTheme";
import { Bootstrap, getBootstrap } from "@/lib/api";
import { ChatPage } from "@/pages/ChatPage";
import { OnboardingPage } from "@/pages/OnboardingPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { VaultPage } from "@/pages/VaultPage";
import { WikiDetailPage } from "@/pages/WikiDetailPage";
import { WikiPage } from "@/pages/WikiPage";

export function App() {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [error, setError] = useState("");
  const theme = useTheme();

  useEffect(() => {
    void getBootstrap().then(setBootstrap).catch((exc) => {
      setError(exc instanceof Error ? exc.message : "서버에 연결할 수 없습니다.");
    });
  }, []);

  if (error) {
    return (
      <main className="grid min-h-screen place-items-center px-4">
        <div className="max-w-md rounded-lg border p-5">
          <h1 className="text-lg font-semibold">연결 오류</h1>
          <p className="mt-2 text-sm text-muted-foreground">{error}</p>
        </div>
      </main>
    );
  }

  if (!bootstrap) {
    return <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">Loading</div>;
  }

  return (
    <Routes>
      <Route path="/onboarding" element={<OnboardingPage />} />
      <Route element={<AppShell bootstrap={bootstrap} dark={theme.dark} setDark={theme.setDark} />}>
        <Route path="/" element={<RootRedirect bootstrap={bootstrap} />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/vault" element={<VaultPage />} />
        <Route path="/wiki" element={<WikiPage />} />
        <Route path="/wiki/detail" element={<WikiDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}

function RootRedirect({ bootstrap }: { bootstrap: Bootstrap }) {
  const location = useLocation();
  if (!bootstrap.onboarding_completed || !bootstrap.vault_path) {
    return <Navigate to="/onboarding" replace state={{ from: location }} />;
  }
  return <Navigate to="/chat" replace />;
}
