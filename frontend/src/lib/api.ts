export type Citation = {
  source: string;
  location?: string;
  page?: number | null;
  doc_type?: string | null;
  kind?: "document" | "mcp" | "wiki" | "web";
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
  wiki_count?: number;
  raw_count?: number;
  used_web_search?: boolean;
  web_search_requested?: boolean;
  web_search_error?: string;
};

export type ChatChunk = {
  kind: "meta" | "token" | "done" | "error";
  text?: string;
  citations?: Citation[];
  used_mcp?: boolean;
  rewritten_question?: string | null;
  retrieval_count?: number;
  wiki_count?: number;
  raw_count?: number;
  used_web_search?: boolean;
  web_search_requested?: boolean;
  web_search_error?: string;
};

export type Bootstrap = {
  title: string;
  description: string;
  onboarding_completed: boolean;
  vault_path: string;
  api_key_configured: boolean;
  indexed_files: number;
  last_sync_at?: string | null;
  wiki?: WikiStatus;
};

export type VaultStatus = {
  vault_path: string;
  onboarding_completed: boolean;
  last_sync_at?: string | null;
  sync_history: SyncHistoryEntry[];
  indexed_files: number;
  api_key_configured: boolean;
  wiki?: WikiStatus;
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
  wiki: Record<string, number | string | boolean>;
  vault: Record<string, unknown>;
  mcp: Record<string, unknown>;
  ui: Record<string, unknown>;
  api_key_configured: boolean;
};

export type McpServer = {
  name: string;
  transport: "stdio" | "http" | "streamable_http" | "sse" | "websocket" | string;
  command?: string | null;
  args: string[];
  env: Record<string, string>;
  url?: string | null;
  headers: Record<string, string>;
  cwd?: string | null;
  timeout?: number | null;
  sse_read_timeout?: number | null;
  terminate_on_close?: boolean | null;
  enabled: boolean;
};

export type McpStatus = {
  enabled: boolean;
  available: boolean;
  error?: string | null;
  connection_checked?: boolean;
  tools: string[];
  web_search_configured?: boolean;
  web_search_available?: boolean;
  web_search_tool?: string;
  servers: string[];
  enabled_servers: string[];
  server: string;
};

export type WikiStatus = {
  enabled: boolean;
  configured: boolean;
  path: string;
  page_count: number;
  generated_page_count?: number;
  document_count?: number;
  indexed_chunks: number;
  source_count: number;
  last_built_at?: string | null;
  error?: string;
};

export type WikiPageSummary = {
  id: string;
  path: string;
  title: string;
  section: string;
  size: number;
  updated_at: string;
  excerpt: string;
};

export type WikiPageContent = WikiPageSummary & {
  content: string;
  linked_source_pages?: string[];
};

export type WikiBuildResult = {
  pages_written: number;
  indexed_chunks: number;
  sources_processed: number;
  sources_skipped: number;
  duration_s: number;
  error?: string;
};

export type WikiLintIssue = {
  severity: "info" | "warning" | "error";
  code: string;
  message: string;
  page?: string;
  metadata?: Record<string, unknown>;
};

export type WikiGraphNode = {
  id: string;
  label: string;
  kind: "concept" | "source" | "page";
  page_id: string;
  source_path?: string;
};

export type WikiGraphEdge = {
  source: string;
  target: string;
  label?: string;
};

export type WikiGraph = {
  nodes: WikiGraphNode[];
  edges: WikiGraphEdge[];
};

export type WikiEasyIndexMatch = {
  kind: "wiki" | "document";
  page_id: string;
  page_title: string;
  source: string;
  snippet: string;
  score: number;
};

export type WikiEasyIndexResult = {
  source: string;
  title: string;
  doc_type: string;
  score: number;
  excerpt: string;
  concepts: string[];
  matches: WikiEasyIndexMatch[];
};

export type WikiEasyIndexResponse = {
  query: string;
  semantic_available: boolean;
  error?: string;
  results: WikiEasyIndexResult[];
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

export async function getMcpStatus(connect = false): Promise<McpStatus> {
  return request(`/api/settings/mcp/status${connect ? "?connect=true" : ""}`);
}

export async function getMcpServers(): Promise<McpServer[]> {
  const response = await request<{ servers: McpServer[] }>("/api/settings/mcp/servers");
  return response.servers;
}

export async function createMcpServer(server: McpServer): Promise<McpServer[]> {
  const response = await request<{ servers: McpServer[] }>("/api/settings/mcp/servers", {
    method: "POST",
    body: JSON.stringify(server),
  });
  return response.servers;
}

export async function updateMcpServer(name: string, server: McpServer): Promise<McpServer[]> {
  const response = await request<{ servers: McpServer[] }>(`/api/settings/mcp/servers/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify(server),
  });
  return response.servers;
}

export async function deleteMcpServer(name: string): Promise<McpServer[]> {
  const response = await request<{ servers: McpServer[] }>(`/api/settings/mcp/servers/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  return response.servers;
}

export async function setApiKey(apiKey: string): Promise<Settings> {
  return request("/api/settings/api-key", {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export async function clearIndex(): Promise<{ deleted_chunks: number }> {
  return request("/api/index/clear", {
    method: "POST",
    body: JSON.stringify({ force: true }),
  });
}

export async function getWikiStatus(): Promise<WikiStatus> {
  return request("/api/wiki/status");
}

export async function getWikiPages(q = ""): Promise<WikiPageSummary[]> {
  const suffix = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
  return request(`/api/wiki/pages${suffix}`);
}

export async function getWikiPage(id: string): Promise<WikiPageContent> {
  return request(`/api/wiki/page?id=${encodeURIComponent(id)}`);
}

export async function rebuildWiki(force = true): Promise<WikiBuildResult> {
  return request(`/api/wiki/rebuild?force=${force ? "true" : "false"}`, { method: "POST" });
}

export async function getWikiLint(): Promise<WikiLintIssue[]> {
  return request("/api/wiki/lint");
}

export async function getWikiGraph(): Promise<WikiGraph> {
  return request("/api/wiki/graph");
}

export async function easyIndexWiki(q: string, limit = 8): Promise<WikiEasyIndexResponse> {
  return request(`/api/wiki/easy-index?q=${encodeURIComponent(q.trim())}&limit=${limit}`);
}

export async function openFile(source: string): Promise<void> {
  await request(`/api/vault/files/open?source=${encodeURIComponent(source)}`);
}

export async function* streamChat(question: string, history: ChatMessage[], webSearch = false): AsyncGenerator<ChatChunk> {
  yield* requestStream<ChatChunk>("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({ question, history, web_search: webSearch }),
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
