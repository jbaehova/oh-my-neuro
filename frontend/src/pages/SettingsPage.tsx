import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Gauge,
  KeyRound,
  Pencil,
  PlugZap,
  Plus,
  RefreshCw,
  Save,
  Server,
  Trash2,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  clearIndex,
  createMcpServer,
  deleteMcpServer,
  getMcpServers,
  getMcpStatus,
  getSettings,
  McpServer,
  McpStatus,
  patchSettings,
  setApiKey,
  Settings,
  updateMcpServer,
} from "@/lib/api";

const EMPTY_SERVER: McpServer = {
  name: "",
  transport: "stdio",
  command: "",
  args: [],
  env: {},
  url: "",
  headers: {},
  cwd: "",
  timeout: null,
  sse_read_timeout: null,
  terminate_on_close: null,
  enabled: true,
};

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [mcpStatus, setMcpStatus] = useState<McpStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const retrieval = settings?.retrieval || {};
  const wiki = settings?.wiki || {};
  const mcp = settings?.mcp || {};
  const llm = settings?.llm || {};

  async function load() {
    setError(null);
    try {
      const [nextSettings, nextServers, nextStatus] = await Promise.all([
        getSettings(),
        getMcpServers(),
        getMcpStatus(),
      ]);
      setSettings(nextSettings);
      setServers(nextServers);
      setMcpStatus(nextStatus);
    } catch (e) {
      setError(e instanceof Error ? e.message : "설정을 불러오지 못했습니다.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function savePatch(payload: Record<string, unknown>) {
    setSaving(true);
    setError(null);
    try {
      const next = await patchSettings(payload);
      setSettings(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  async function updateRetrieval(key: string, value: number | boolean) {
    await savePatch({ retrieval: { [key]: value } });
  }

  async function updateLlm(key: string, value: string | number) {
    await savePatch({ llm: { [key]: value } });
  }

  async function updateMcp(enabled: boolean) {
    await savePatch({ mcp: { enabled } });
    void refreshMcpStatus();
  }

  async function updateWiki(key: string, value: boolean) {
    await savePatch({ wiki: { [key]: value } });
  }

  async function refreshMcpStatus(connect = false) {
    try {
      setMcpStatus(await getMcpStatus(connect));
    } catch (e) {
      setError(e instanceof Error ? e.message : "MCP 상태를 불러오지 못했습니다.");
    }
  }

  async function replaceServers(next: McpServer[]) {
    setServers(next);
    await refreshMcpStatus(false);
  }

  async function runClear() {
    const confirmation = window.prompt("전체 인덱스를 삭제하려면 CLEAR를 입력하세요.");
    if (confirmation !== "CLEAR") return;
    await clearIndex();
  }

  return (
    <>
      <PageHeader
        title="Settings"
        description="OMN의 응답 품질, 속도, 외부 도구 연결을 조정합니다. 변경 사항은 현재 실행 중인 서버에 즉시 적용됩니다."
        action={
          <div className="flex flex-wrap items-center gap-2">
            {saving ? <Badge variant="outline">저장 중</Badge> : null}
            <Badge variant={settings?.api_key_configured ? "secondary" : "warning"}>
              {settings?.api_key_configured ? "OPENAI_API_KEY OK" : "OPENAI_API_KEY 없음"}
            </Badge>
          </div>
        }
      />

      {error ? (
        <div className="mb-5 rounded-lg border border-destructive/30 bg-destructive/[0.06] px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {settings && !settings.api_key_configured ? <ApiKeyCard onSaved={setSettings} /> : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-6">
          <section className="surface rounded-lg p-5">
            <SectionTitle
              icon={Gauge}
              title="LLM 속도와 모델"
              description="답변 생성 모델은 품질에, 재작성/검증 모델은 검색 준비 속도에 영향을 줍니다."
            />
            <div className="mt-4 grid gap-4 md:grid-cols-3">
              <TextSetting
                label="답변 모델"
                value={String(llm.chat_model || "")}
                description="최종 답변을 작성하는 모델입니다. 품질을 우선하면 mini 이상, 속도를 우선하면 더 작은 모델을 사용하세요."
                onSave={(v) => updateLlm("chat_model", v)}
              />
              <TextSetting
                label="질문 재작성 모델"
                value={String(llm.rewriter_model || "")}
                description="후속 질문을 독립 질문으로 바꿉니다. nano 계열을 쓰면 대화형 검색 준비가 빨라집니다."
                onSave={(v) => updateLlm("rewriter_model", v)}
              />
              <TextSetting
                label="문서 검증 모델"
                value={String(llm.grader_model || "")}
                description="LLM 문서 검증을 켤 때만 사용됩니다. 기본은 벡터 점수 기반 필터입니다."
                onSave={(v) => updateLlm("grader_model", v)}
              />
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <NumberSetting
                label="요청 제한 시간"
                value={Number(llm.request_timeout ?? 60)}
                min={10}
                max={180}
                suffix="초"
                description="OpenAI 호출 하나가 기다릴 최대 시간입니다. 너무 낮으면 긴 문서 답변이 중단될 수 있습니다."
                onSave={(v) => updateLlm("request_timeout", v)}
              />
              <NumberSetting
                label="Temperature x100"
                value={Math.round(Number(llm.temperature ?? 0.2) * 100)}
                min={0}
                max={100}
                description="값이 낮을수록 답변이 안정적이고 반복 가능해집니다. 저장 시 100으로 나눈 값이 적용됩니다."
                onSave={(v) => updateLlm("temperature", v / 100)}
              />
            </div>
          </section>

          <section className="surface rounded-lg p-5">
            <SectionTitle
              icon={RefreshCw}
              title="검색 파이프라인"
              description="검색량과 필터링 방식을 조정합니다. 빠른 데모에는 LLM 문서 검증 OFF, Max rewrites 0-1이 적합합니다."
            />
            <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              <NumberSetting
                label="Top K"
                value={Number(retrieval.top_k ?? 5)}
                min={1}
                max={20}
                description="최종 답변에 넣을 문서 조각 수입니다. 값이 클수록 근거는 늘지만 답변 생성이 느려집니다."
                onSave={(v) => updateRetrieval("top_k", v)}
              />
              <NumberSetting
                label="Fetch K"
                value={Number(retrieval.fetch_k ?? 12)}
                min={1}
                max={50}
                description="후보로 먼저 가져올 문서 조각 수입니다. Top K보다 크거나 같게 두는 것이 안전합니다."
                onSave={(v) => updateRetrieval("fetch_k", v)}
              />
              <NumberSetting
                label="Chunk size"
                value={Number(retrieval.chunk_size ?? 1000)}
                min={200}
                max={3000}
                description="인덱싱 때 문서를 자르는 기본 글자 수입니다. 변경 후에는 Vault 재동기화가 필요합니다."
                onSave={(v) => updateRetrieval("chunk_size", v)}
              />
              <NumberSetting
                label="Chunk overlap"
                value={Number(retrieval.chunk_overlap ?? 150)}
                min={0}
                max={1000}
                description="인접 조각 사이에 겹쳐 넣을 글자 수입니다. 문맥 보존에 도움되지만 인덱스가 커집니다."
                onSave={(v) => updateRetrieval("chunk_overlap", v)}
              />
              <NumberSetting
                label="Max rewrites"
                value={Number(retrieval.max_rewrites ?? 1)}
                min={0}
                max={5}
                description="검색 결과가 부족할 때 질문을 다시 써서 재검색하는 횟수입니다. 속도 우선이면 0으로 둡니다."
                onSave={(v) => updateRetrieval("max_rewrites", v)}
              />
              <NumberSetting
                label="Threshold x100"
                value={Math.round(Number(retrieval.relevance_threshold ?? 0.5) * 100)}
                min={0}
                max={100}
                description="벡터 점수 기반 문서 필터 기준입니다. 낮추면 더 많이 통과하고 높이면 더 엄격해집니다."
                onSave={(v) => updateRetrieval("relevance_threshold", v / 100)}
              />
            </div>
            <div className="mt-5 flex items-start justify-between gap-4 rounded-lg border bg-background/60 p-4">
              <div>
                <div className="text-sm font-medium">LLM 문서 검증</div>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  ON이면 검색 후보마다 모델이 관련성을 다시 판단합니다. 정확도 검증에는 좋지만 응답 속도가 크게 느려질 수 있습니다.
                </p>
              </div>
              <Switch
                checked={Boolean(retrieval.use_llm_grader)}
                onCheckedChange={(checked) => updateRetrieval("use_llm_grader", checked)}
              />
            </div>
          </section>

          <McpSection
            enabled={Boolean(mcp.enabled)}
            configPath={String(mcp.user_config_path || mcp.config_path || "-")}
            lawServer={String(mcp.law_server || "-")}
            status={mcpStatus}
            servers={servers}
            onToggle={updateMcp}
            onRefresh={() => refreshMcpStatus(true)}
            onCreate={async (server) => replaceServers(await createMcpServer(server))}
            onUpdate={async (name, server) => replaceServers(await updateMcpServer(name, server))}
            onDelete={async (name) => replaceServers(await deleteMcpServer(name))}
          />
        </div>

        <aside className="space-y-6">
          <section className="surface rounded-lg p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold">Wiki</h2>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  Vault 문서를 요약해 별도 Markdown 지식 레이어를 만듭니다. 생성물은 Vault 내부의 Wiki 디렉토리에 저장됩니다.
                </p>
              </div>
              <Switch checked={Boolean(wiki.enabled)} onCheckedChange={(checked) => updateWiki("enabled", checked)} />
            </div>
            <div className="mt-4 flex items-center justify-between gap-3">
              <div>
                <div className="text-xs font-medium">Sync 때 갱신</div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  Vault SYNC 후 Wiki를 자동 재생성합니다. 데모 준비 중 시간이 오래 걸리면 잠시 끌 수 있습니다.
                </div>
              </div>
              <Switch checked={Boolean(wiki.update_on_sync)} onCheckedChange={(checked) => updateWiki("update_on_sync", checked)} />
            </div>
            <dl className="mt-4 space-y-2 text-xs text-muted-foreground">
              <div>
                <dt className="font-medium text-foreground/70">Directory</dt>
                <dd className="mt-0.5 break-all">{String(wiki.directory || "-")}</dd>
              </div>
              <div>
                <dt className="font-medium text-foreground/70">Collection</dt>
                <dd className="mt-0.5 break-all">{String(wiki.collection_name || "-")}</dd>
              </div>
            </dl>
          </section>

          <section className="rounded-lg border border-destructive/30 p-5">
            <h2 className="text-base font-semibold">Danger zone</h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              저장된 ChromaDB 인덱스를 비웁니다. Vault 원본 파일은 삭제하지 않습니다.
            </p>
            <Button className="mt-4 w-full" variant="destructive" onClick={runClear}>
              <Trash2 className="size-4" />
              인덱스 초기화
            </Button>
          </section>
        </aside>
      </div>
    </>
  );
}

function SectionTitle({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-secondary">
        <Icon className="size-4 text-muted-foreground" />
      </div>
      <div>
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

function ApiKeyCard({ onSaved }: { onSaved: (settings: Settings) => void }) {
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    const key = draft.trim();
    if (!key) {
      setError("API 키를 입력하세요.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const next = await setApiKey(key);
      setDraft("");
      onSaved(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="surface mb-6 rounded-lg border border-accent/30 bg-accent/10 p-5">
      <div className="flex items-center gap-2">
        <KeyRound className="size-4 text-accent" />
        <h2 className="text-base font-semibold">OpenAI API 키 설정이 필요합니다</h2>
      </div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        답변 생성과 문서 검색에는 OpenAI API 키가 필요합니다. 저장하면 프로젝트 루트의
        <code className="mx-1 rounded bg-muted px-1">.env</code> 파일에 반영되고 즉시 적용됩니다.
      </p>

      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <Input
          type="password"
          autoComplete="off"
          placeholder="sk-..."
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void save();
          }}
        />
        <Button onClick={() => void save()} disabled={saving} type="button">
          <Save className="size-4" />
          {saving ? "저장 중..." : "저장"}
        </Button>
      </div>
      {error ? <p className="mt-2 text-xs text-destructive">{error}</p> : null}
    </section>
  );
}

function TextSetting({
  label,
  value,
  description,
  onSave,
}: {
  label: string;
  value: string;
  description: string;
  onSave: (value: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  return (
    <label className="block">
      <span className="text-xs font-medium text-foreground">{label}</span>
      <p className="mt-1 min-h-10 text-xs leading-5 text-muted-foreground">{description}</p>
      <div className="mt-2 flex gap-2">
        <Input value={draft} onChange={(event) => setDraft(event.target.value)} />
        <Button variant="outline" size="icon" onClick={() => onSave(draft.trim())} type="button" title={`${label} 저장`}>
          <Save className="size-4" />
        </Button>
      </div>
    </label>
  );
}

function NumberSetting({
  label,
  value,
  min,
  max,
  suffix,
  description,
  onSave,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  suffix?: string;
  description: string;
  onSave: (value: number) => Promise<void>;
}) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  return (
    <label className="block">
      <span className="text-xs font-medium text-foreground">{label}</span>
      <p className="mt-1 min-h-10 text-xs leading-5 text-muted-foreground">{description}</p>
      <div className="mt-2 flex gap-2">
        <Input
          type="number"
          min={min}
          max={max}
          value={draft}
          onChange={(event) => setDraft(Number(event.target.value))}
        />
        {suffix ? <span className="flex h-9 items-center text-xs text-muted-foreground">{suffix}</span> : null}
        <Button variant="outline" size="icon" onClick={() => onSave(draft)} type="button" title={`${label} 저장`}>
          <Save className="size-4" />
        </Button>
      </div>
    </label>
  );
}

function McpSection({
  enabled,
  configPath,
  lawServer,
  status,
  servers,
  onToggle,
  onRefresh,
  onCreate,
  onUpdate,
  onDelete,
}: {
  enabled: boolean;
  configPath: string;
  lawServer: string;
  status: McpStatus | null;
  servers: McpServer[];
  onToggle: (enabled: boolean) => Promise<void>;
  onRefresh: () => Promise<void>;
  onCreate: (server: McpServer) => Promise<void>;
  onUpdate: (name: string, server: McpServer) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
}) {
  const [editingName, setEditingName] = useState<string | null>(null);
  const [draft, setDraft] = useState<McpServer>(EMPTY_SERVER);
  const [formError, setFormError] = useState<string | null>(null);

  const editingServer = useMemo(
    () => servers.find((server) => server.name === editingName) || null,
    [editingName, servers],
  );

  useEffect(() => {
    setDraft(editingServer ? cloneServer(editingServer) : EMPTY_SERVER);
  }, [editingServer]);

  function startCreate() {
    setEditingName(null);
    setDraft(EMPTY_SERVER);
    setFormError(null);
  }

  function startEdit(server: McpServer) {
    setEditingName(server.name);
    setDraft(cloneServer(server));
    setFormError(null);
  }

  async function saveServer() {
    const normalized = normalizeServer(draft);
    if (!normalized.name) {
      setFormError("서버 이름을 입력하세요.");
      return;
    }
    setFormError(null);
    try {
      if (editingName) {
        await onUpdate(editingName, normalized);
      } else {
        await onCreate(normalized);
      }
      startCreate();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "MCP 서버 저장에 실패했습니다.");
    }
  }

  async function removeServer(name: string) {
    const confirmation = window.confirm(`${name} MCP 서버를 삭제할까요?`);
    if (!confirmation) return;
    try {
      await onDelete(name);
      if (editingName === name) startCreate();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "MCP 서버 삭제에 실패했습니다.");
    }
  }

  return (
    <section className="surface rounded-lg p-5">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <SectionTitle
          icon={PlugZap}
          title="MCP 서버와 웹검색"
          description="외부 도구 서버를 연결합니다. 웹검색 ON/OFF는 Chat 입력창에서 고르고, 실제 검색은 여기 연결된 검색 MCP 도구로 수행됩니다."
        />
        <div className="flex shrink-0 items-center gap-3">
          <Badge variant={status?.web_search_available || status?.web_search_configured ? "secondary" : "outline"}>
            {status?.web_search_available
              ? "웹검색 연결됨"
              : status?.web_search_configured
                ? "웹검색 서버 등록됨"
                : "웹검색 서버 없음"}
          </Badge>
          <Switch checked={enabled} onCheckedChange={onToggle} />
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <McpMetric
          label="상태"
          value={status?.available ? "연결됨" : enabled ? status?.connection_checked ? "오류/미연결" : "연결 전" : "비활성"}
        />
        <McpMetric label="도구 수" value={`${status?.tools.length ?? 0}`} />
        <McpMetric label="법령 서버" value={lawServer} />
        <McpMetric label="설정 파일" value={configPath} />
      </div>
      {status?.error ? (
        <p className="mt-3 rounded-md border border-accent/30 bg-accent/[0.08] px-3 py-2 text-xs leading-5 text-muted-foreground">
          {status.error}
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => void onRefresh()}>
          <RefreshCw className="size-3.5" />
          연결 테스트
        </Button>
        <Button variant="secondary" size="sm" onClick={startCreate}>
          <Plus className="size-3.5" />
          새 서버
        </Button>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-secondary text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">서버</th>
                <th className="hidden px-3 py-2 text-left font-medium md:table-cell">연결 방식</th>
                <th className="hidden px-3 py-2 text-left font-medium lg:table-cell">엔드포인트</th>
                <th className="px-3 py-2 text-right font-medium">관리</th>
              </tr>
            </thead>
            <tbody>
              {servers.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-3 py-8 text-center text-sm text-muted-foreground">
                    등록된 MCP 서버가 없습니다.
                  </td>
                </tr>
              ) : (
                servers.map((server) => (
                  <tr key={server.name} className="border-t">
                    <td className="min-w-0 px-3 py-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <Server className="size-4 shrink-0 text-muted-foreground" />
                        <div className="min-w-0">
                          <div className="truncate font-medium">{server.name}</div>
                          <div className="text-xs text-muted-foreground">{server.enabled ? "활성" : "비활성"}</div>
                        </div>
                      </div>
                    </td>
                    <td className="hidden px-3 py-2 text-muted-foreground md:table-cell">{server.transport}</td>
                    <td className="hidden max-w-[280px] truncate px-3 py-2 text-muted-foreground lg:table-cell">
                      {server.transport === "stdio" ? [server.command, ...(server.args || [])].filter(Boolean).join(" ") : server.url || "-"}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="icon" className="size-8" onClick={() => startEdit(server)} title="수정">
                          <Pencil className="size-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="size-8" onClick={() => void removeServer(server.name)} title="삭제">
                          <Trash2 className="size-3.5" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="rounded-lg border bg-background/70 p-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">{editingName ? "MCP 서버 수정" : "MCP 서버 추가"}</h3>
            {editingName ? (
              <Button variant="ghost" size="icon" className="size-8" onClick={startCreate} title="편집 취소">
                <X className="size-3.5" />
              </Button>
            ) : null}
          </div>

          <div className="mt-4 space-y-3">
            <Field label="서버 이름" help="영문, 숫자, '.', '_', '-'만 사용할 수 있습니다. 예: brave_search">
              <Input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
            </Field>
            <Field label="연결 방식" help="로컬 명령 실행은 stdio, 원격 서버는 streamable_http 또는 sse를 사용합니다.">
              <select
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={draft.transport}
                onChange={(event) => setDraft({ ...draft, transport: event.target.value })}
              >
                <option value="stdio">stdio</option>
                <option value="streamable_http">streamable_http</option>
                <option value="sse">sse</option>
                <option value="websocket">websocket</option>
              </select>
            </Field>
            {draft.transport === "stdio" ? (
              <>
                <Field label="Command" help="예: uvx, npx, python">
                  <Input value={draft.command || ""} onChange={(event) => setDraft({ ...draft, command: event.target.value })} />
                </Field>
                <Field label="Args" help="한 줄에 하나씩 입력합니다. 예: @modelcontextprotocol/server-brave-search">
                  <Textarea
                    className="min-h-[72px]"
                    value={(draft.args || []).join("\n")}
                    onChange={(event) => setDraft({ ...draft, args: splitLines(event.target.value) })}
                  />
                </Field>
              </>
            ) : (
              <Field label="URL" help="원격 MCP 서버의 전체 URL입니다.">
                <Input value={draft.url || ""} onChange={(event) => setDraft({ ...draft, url: event.target.value })} />
              </Field>
            )}
            <Field label="환경 변수" help="한 줄에 KEY=value 형식으로 입력합니다. 비밀 값은 가능하면 $ENV_NAME 참조로 넣으세요.">
              <Textarea
                className="min-h-[72px]"
                value={formatPairs(draft.env)}
                onChange={(event) => setDraft({ ...draft, env: parsePairs(event.target.value) })}
              />
            </Field>
            {draft.transport !== "stdio" ? (
              <Field label="Headers" help="한 줄에 KEY=value 형식입니다. Authorization 헤더도 $ENV_NAME 참조를 권장합니다.">
                <Textarea
                  className="min-h-[72px]"
                  value={formatPairs(draft.headers)}
                  onChange={(event) => setDraft({ ...draft, headers: parsePairs(event.target.value) })}
                />
              </Field>
            ) : null}
            <div className="flex items-center justify-between rounded-md border bg-muted/20 px-3 py-2">
              <div>
                <div className="text-xs font-medium">활성화</div>
                <div className="mt-0.5 text-xs text-muted-foreground">OFF면 저장은 되지만 연결 대상에서 제외됩니다.</div>
              </div>
              <Switch checked={draft.enabled} onCheckedChange={(checked) => setDraft({ ...draft, enabled: checked })} />
            </div>
          </div>

          {formError ? <p className="mt-3 text-xs leading-5 text-destructive">{formError}</p> : null}
          <Button className="mt-4 w-full" onClick={() => void saveServer()}>
            <Save className="size-4" />
            {editingName ? "수정 저장" : "서버 추가"}
          </Button>
        </div>
      </div>
    </section>
  );
}

function McpMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border bg-background/60 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate text-xs font-medium">{value}</div>
    </div>
  );
}

function Field({ label, help, children }: { label: string; help: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-medium">{label}</span>
      <p className="mt-0.5 text-xs leading-5 text-muted-foreground">{help}</p>
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

function cloneServer(server: McpServer): McpServer {
  return {
    ...server,
    args: [...(server.args || [])],
    env: { ...(server.env || {}) },
    headers: { ...(server.headers || {}) },
  };
}

function normalizeServer(server: McpServer): McpServer {
  return {
    ...server,
    name: server.name.trim(),
    transport: server.transport.trim() || "stdio",
    command: cleanOptional(server.command),
    url: cleanOptional(server.url),
    cwd: cleanOptional(server.cwd),
    args: (server.args || []).map((arg) => arg.trim()).filter(Boolean),
    env: cleanPairs(server.env),
    headers: cleanPairs(server.headers),
  };
}

function cleanOptional(value?: string | null) {
  const next = (value || "").trim();
  return next || null;
}

function splitLines(value: string) {
  return value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

function parsePairs(value: string) {
  const out: Record<string, string> = {};
  value.split(/\r?\n/).forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    const eq = trimmed.indexOf("=");
    if (eq === -1) return;
    const key = trimmed.slice(0, eq).trim();
    const val = trimmed.slice(eq + 1).trim();
    if (key) out[key] = val;
  });
  return out;
}

function formatPairs(value: Record<string, string>) {
  return Object.entries(value || {}).map(([key, val]) => `${key}=${val}`).join("\n");
}

function cleanPairs(value: Record<string, string>) {
  const out: Record<string, string> = {};
  Object.entries(value || {}).forEach(([key, val]) => {
    const cleanKey = key.trim();
    if (cleanKey) out[cleanKey] = String(val).trim();
  });
  return out;
}
