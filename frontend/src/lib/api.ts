export type Bootstrap = {
  title: string;
  description: string;
  onboarding_completed: boolean;
  vault_path: string;
  api_key_configured: boolean;
  indexed_files: number;
  last_sync_at?: string | null;
};

export type Health = {
  ok: boolean;
  app: string;
  api_key_configured: boolean;
};

export async function getBootstrap(): Promise<Bootstrap> {
  return request("/api/bootstrap");
}

export async function getHealth(): Promise<Health> {
  return request("/api/health");
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

async function readError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    return data.detail || data.message || response.statusText;
  } catch {
    return response.statusText;
  }
}
