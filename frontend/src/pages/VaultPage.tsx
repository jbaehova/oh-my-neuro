import { useEffect, useMemo, useState } from "react";
import { FolderOpen, RefreshCw, Search, Trash2 } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { clearIndex, getFiles, getVaultStatus, IndexedFile, streamSync, SyncEvent, VaultStatus } from "@/lib/api";

export function VaultPage() {
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [files, setFiles] = useState<IndexedFile[]>([]);
  const [query, setQuery] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncEvent, setSyncEvent] = useState<SyncEvent | null>(null);

  async function load() {
    const [nextStatus, nextFiles] = await Promise.all([getVaultStatus(), getFiles()]);
    setStatus(nextStatus);
    setFiles(nextFiles);
  }

  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return files;
    return files.filter((file) => file.source.toLowerCase().includes(q));
  }, [files, query]);

  const hasVaultPath = Boolean(status?.vault_path?.trim());
  const syncDisabled = syncing || !hasVaultPath;

  async function runSync() {
    if (!hasVaultPath) {
      setSyncEvent({ kind: "error", text: "Vault 경로를 먼저 설정해주세요." });
      return;
    }
    setSyncing(true);
    setSyncEvent({ kind: "progress", file: "", stage: "준비 중", fraction: null });
    try {
      for await (const event of streamSync()) {
        setSyncEvent(event);
      }
      await load();
    } finally {
      setSyncing(false);
    }
  }

  async function runClear() {
    const confirmation = window.prompt("전체 인덱스를 삭제하려면 CLEAR를 입력하세요.");
    if (confirmation !== "CLEAR") return;
    await clearIndex();
    await load();
  }

  return (
    <>
      <PageHeader
        title="Vault"
        description="선택한 로컬 디렉토리의 문서를 ChromaDB 인덱스와 동기화합니다."
        action={
          <Button onClick={runSync} disabled={syncDisabled} title={!hasVaultPath ? "Vault 경로를 먼저 설정해주세요." : undefined}>
            <RefreshCw className={syncing ? "size-4 animate-spin" : "size-4"} />
            SYNC
          </Button>
        }
      />

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Vault 경로" value={status?.vault_path || "미설정"} />
        <Metric label="인덱싱 파일" value={`${status?.indexed_files ?? files.length}`} />
        <Metric label="마지막 SYNC" value={relativeTime(status?.last_sync_at)} />
        <Metric label="API Key" value={status?.api_key_configured ? "설정됨" : "없음"} />
      </section>

      {syncEvent && (
        <section className="surface mt-5 rounded-lg p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-medium">
                {syncEvent.kind === "progress" ? syncEvent.stage : syncEvent.kind === "done" ? "완료" : "오류"}
              </div>
              <div className="mt-1 truncate text-xs text-muted-foreground">
                {syncEvent.kind === "progress" ? syncEvent.file || "작업 대기 중" : syncEvent.kind === "error" ? syncEvent.text : "인덱스가 갱신되었습니다."}
              </div>
            </div>
            {syncEvent.kind === "done" && <Badge variant="secondary">done</Badge>}
          </div>
          <Progress
            className="mt-3"
            value={syncEvent.kind === "progress" && typeof syncEvent.fraction === "number" ? syncEvent.fraction * 100 : syncEvent.kind === "done" ? 100 : null}
          />
        </section>
      )}

      <section className="mt-7">
        <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative w-full max-w-md">
            <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" />
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="파일 검색" className="pl-9" />
          </div>
          <Badge variant="outline">{filtered.length} files</Badge>
        </div>

        {filtered.length === 0 ? (
          <EmptyState
            title="인덱싱된 파일이 없습니다"
            description="Vault 경로를 설정한 뒤 SYNC를 실행하면 파일 목록이 표시됩니다."
            action={
              <Button onClick={runSync} disabled={syncDisabled} title={!hasVaultPath ? "Vault 경로를 먼저 설정해주세요." : undefined}>
                SYNC 실행
              </Button>
            }
          />
        ) : (
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-secondary text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">파일</th>
                  <th className="hidden px-3 py-2 text-left font-medium sm:table-cell">형식</th>
                  <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">크기</th>
                  <th className="px-3 py-2 text-right font-medium">동기화</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((file) => (
                  <tr key={file.source} className="border-t">
                    <td className="min-w-0 px-3 py-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <FolderOpen className="size-4 text-muted-foreground" />
                        <span className="truncate">{file.source}</span>
                      </div>
                    </td>
                    <td className="hidden px-3 py-2 text-muted-foreground sm:table-cell">{file.doc_type || "-"}</td>
                    <td className="hidden px-3 py-2 text-right text-muted-foreground sm:table-cell">{formatBytes(file.size)}</td>
                    <td className="px-3 py-2 text-right text-muted-foreground">{relativeTime(file.synced_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="mt-7 rounded-lg border border-destructive/30 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-sm font-medium">인덱스 초기화</div>
            <div className="text-xs text-muted-foreground">Vault 파일은 삭제하지 않고 ChromaDB 인덱스만 비웁니다.</div>
          </div>
          <Button variant="destructive" onClick={runClear}>
            <Trash2 className="size-4" />
            Clear
          </Button>
        </div>
      </section>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface min-w-0 rounded-lg p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold">{value}</div>
    </div>
  );
}

function relativeTime(value?: string | null) {
  if (!value) return "없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "방금";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}시간 전`;
  return `${Math.floor(seconds / 86400)}일 전`;
}

function formatBytes(value: number) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}
