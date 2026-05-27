export type Citation = {
  source: string;
  location?: string;
  page?: number | null;
  doc_type?: string | null;
  kind?: "document" | "mcp";
  snippet?: string | null;
};

export type ChatMessage = {
  role: "user" | "assistant" | "system";
  content: string;
};

export type ChatResponse = {
  answer: string;
  citations: Citation[];
  used_mcp: boolean;
  rewritten_question?: string | null;
  retrieval_count: number;
};

export type ChatChunk = {
  kind: "meta" | "token" | "done" | "error";
  text?: string;
  citations?: Citation[];
  used_mcp?: boolean;
  rewritten_question?: string | null;
  retrieval_count?: number;
};

export type Bootstrap = {
  title: string;
  description: string;
  onboarding_completed: boolean;
  vault_path: string;
  api_key_configured: boolean;
  indexed_files: number;
  last_sync_at?: string | null;
};

export type VaultStatus = {
  vault_path: string;
  onboarding_completed: boolean;
  last_sync_at?: string | null;
  sync_history: SyncHistoryEntry[];
  indexed_files: number;
  api_key_configured: boolean;
};

export type SyncHistoryEntry = {
  at: string;
  added: number;
  updated: number;
  deleted: number;
  skipped: number;
  duration_s: number;
};

export type IndexedFile = {
  source: string;
  doc_type: string;
  size: number;
  synced_at: string;
};

export type SyncEvent =
  | { kind: "progress"; file: string; stage: string; fraction?: number | null }
  | { kind: "done"; result: Record<string, unknown>; skipped?: { path: string; reason: string }[] }
  | { kind: "error"; text: string };

export type Settings = {
  app: Record<string, unknown>;
  llm: Record<string, unknown>;
  retrieval: Record<string, number | string | boolean>;
  storage: Record<string, unknown>;
  vault: Record<string, unknown>;
  mcp: Record<string, unknown>;
  ui: Record<string, unknown>;
  api_key_configured: boolean;
};

export async function getBootstrap(): Promise<Bootstrap> {
  return request("/api/bootstrap");
}

export async function setVaultPath(path: string): Promise<VaultStatus> {
  return request("/api/vault", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function getVaultStatus(): Promise<VaultStatus> {
  return request("/api/vault/status");
}

export async function getFiles(): Promise<IndexedFile[]> {
  const response = await request<{ files: IndexedFile[] }>("/api/vault/files");
  return response.files;
}

export async function getSettings(): Promise<Settings> {
  return request("/api/settings");
}

export async function patchSettings(payload: Record<string, unknown>): Promise<Settings> {
  return request("/api/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function clearIndex(): Promise<{ deleted_chunks: number }> {
  return request("/api/index/clear", {
    method: "POST",
    body: JSON.stringify({ force: true }),
  });
}

export async function* streamChat(question: string, history: ChatMessage[]): AsyncGenerator<ChatChunk> {
  yield* requestStream<ChatChunk>("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({ question, history }),
  });
}

export async function* streamSync(): AsyncGenerator<SyncEvent> {
  yield* requestStream<SyncEvent>("/api/vault/sync", { method: "POST" });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json() as Promise<T>;
}

async function* requestStream<T>(path: string, init?: RequestInit): AsyncGenerator<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok || !response.body) {
    throw new Error(await readError(response));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.trim()) {
        yield JSON.parse(line) as T;
      }
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    yield JSON.parse(buffer) as T;
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    const detail = data.detail || data.message;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((item) => item?.msg || JSON.stringify(item)).join("\n");
    }
    if (detail) return JSON.stringify(detail);
    return response.statusText;
  } catch {
    return response.statusText;
  }
}
