import { useEffect, useState } from "react";
import { Save, Trash2 } from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { clearIndex, getSettings, patchSettings, Settings } from "@/lib/api";

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const retrieval = settings?.retrieval || {};
  const mcp = settings?.mcp || {};

  useEffect(() => {
    void getSettings().then(setSettings);
  }, []);

  async function updateRetrieval(key: string, value: number) {
    if (!settings) return;
    setSaving(true);
    const next = await patchSettings({ retrieval: { [key]: value } });
    setSettings(next);
    setSaving(false);
  }

  async function updateMcp(enabled: boolean) {
    setSaving(true);
    const next = await patchSettings({ mcp: { enabled } });
    setSettings(next);
    setSaving(false);
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
        description="현재 프로세스에 적용되는 검색 및 MCP 설정입니다. 파일 기반 설정은 app.yaml에서 관리합니다."
        action={<Badge variant={settings?.api_key_configured ? "secondary" : "warning"}>{settings?.api_key_configured ? "OPENAI_API_KEY OK" : "OPENAI_API_KEY 없음"}</Badge>}
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <section className="surface rounded-lg p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-base font-semibold">Retrieval</h2>
            {saving && <Badge variant="outline">저장 중</Badge>}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <NumberSetting label="Top K" value={Number(retrieval.top_k ?? 5)} min={1} max={20} onSave={(v) => updateRetrieval("top_k", v)} />
            <NumberSetting label="Fetch K" value={Number(retrieval.fetch_k ?? 12)} min={1} max={50} onSave={(v) => updateRetrieval("fetch_k", v)} />
            <NumberSetting label="Chunk size" value={Number(retrieval.chunk_size ?? 1000)} min={200} max={3000} onSave={(v) => updateRetrieval("chunk_size", v)} />
            <NumberSetting label="Chunk overlap" value={Number(retrieval.chunk_overlap ?? 150)} min={0} max={1000} onSave={(v) => updateRetrieval("chunk_overlap", v)} />
            <NumberSetting label="Max rewrites" value={Number(retrieval.max_rewrites ?? 1)} min={0} max={5} onSave={(v) => updateRetrieval("max_rewrites", v)} />
            <NumberSetting label="Threshold x100" value={Math.round(Number(retrieval.relevance_threshold ?? 0.5) * 100)} min={0} max={100} onSave={(v) => updateRetrieval("relevance_threshold", v / 100)} />
          </div>
        </section>

        <aside className="space-y-6">
          <section className="surface rounded-lg p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold">MCP</h2>
                <p className="mt-1 text-xs text-muted-foreground">법령 키워드 라우팅에 사용합니다.</p>
              </div>
              <Switch checked={Boolean(mcp.enabled)} onCheckedChange={updateMcp} />
            </div>
            <div className="mt-4 space-y-2 text-xs text-muted-foreground">
              <div>Server: {String(mcp.law_server || "-")}</div>
              <div>Config: {String(mcp.config_path || "-")}</div>
            </div>
          </section>

          <section className="rounded-lg border border-destructive/30 p-5">
            <h2 className="text-base font-semibold">Danger zone</h2>
            <p className="mt-1 text-xs text-muted-foreground">저장된 ChromaDB 인덱스를 비웁니다.</p>
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

function NumberSetting({
  label,
  value,
  min,
  max,
  onSave,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onSave: (value: number) => Promise<void>;
}) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  return (
    <label className="block">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="mt-1 flex gap-2">
        <Input type="number" min={min} max={max} value={draft} onChange={(event) => setDraft(Number(event.target.value))} />
        <Button variant="outline" size="icon" onClick={() => onSave(draft)} type="button">
          <Save className="size-4" />
        </Button>
      </div>
    </label>
  );
}

