import { useEffect, useMemo, useState } from "react";

import type { ChatMessage } from "@/lib/api";

type SessionIndex = {
  id: string;
  title: string;
  updated_at: string;
};

const INDEX_KEY = "omn-react-sessions";

const SYNC_EVENT = "omn-sessions-updated";

export function useSessions() {
  const [sessions, setSessions] = useState<SessionIndex[]>(readIndex);

  useEffect(() => {
    const onUpdate = () => setSessions(readIndex());
    window.addEventListener(SYNC_EVENT, onUpdate);
    return () => window.removeEventListener(SYNC_EVENT, onUpdate);
  }, []);

  return useMemo(
    () => ({
      sessions,
      load(id: string): ChatMessage[] {
        const raw = localStorage.getItem(sessionKey(id));
        if (!raw) return [];
        try {
          return JSON.parse(raw) as ChatMessage[];
        } catch {
          return [];
        }
      },
      save(id: string, messages: ChatMessage[]) {
        localStorage.setItem(sessionKey(id), JSON.stringify(messages));
        const title = messages.find((m) => m.role === "user")?.content.slice(0, 48) || "새 대화";
        const next = [
          { id, title, updated_at: new Date().toISOString() },
          ...sessions.filter((s) => s.id !== id),
        ].slice(0, 30);
        localStorage.setItem(INDEX_KEY, JSON.stringify(next));
        setSessions(next);
        window.dispatchEvent(new CustomEvent(SYNC_EVENT));
      },
      remove(id: string) {
        localStorage.removeItem(sessionKey(id));
        const next = sessions.filter((s) => s.id !== id);
        localStorage.setItem(INDEX_KEY, JSON.stringify(next));
        setSessions(next);
        window.dispatchEvent(new CustomEvent(SYNC_EVENT));
      },
    }),
    [sessions],
  );
}

export function newSessionId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function readIndex(): SessionIndex[] {
  try {
    return JSON.parse(localStorage.getItem(INDEX_KEY) || "[]") as SessionIndex[];
  } catch {
    return [];
  }
}

function sessionKey(id: string) {
  return `omn-react-session-${id}`;
}

