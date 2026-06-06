import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  Folder,
  FolderOpen,
  RefreshCw,
  Save,
  Search,
  Trash2,
} from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  clearIndex,
  getFiles,
  getVaultStatus,
  IndexedFile,
  openFile,
  setVaultPath,
  streamSync,
  SyncEvent,
  VaultStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type VaultTreeNode = {
  name: string;
  path: string;
  type: "directory" | "file";
  children: VaultTreeNode[];
  file?: IndexedFile;
};

export function VaultPage() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [files, setFiles] = useState<IndexedFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<IndexedFile | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState(() => params.get("q") || "");
  const [pathDraft, setPathDraft] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncEvent, setSyncEvent] = useState<SyncEvent | null>(null);
  const [pathSaving, setPathSaving] = useState(false);

  async function load() {
    const [nextStatus, nextFiles] = await Promise.all([getVaultStatus(), getFiles()]);
    setStatus(nextStatus);
    setFiles(nextFiles);
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (status?.vault_path && !pathDraft) setPathDraft(status.vault_path);
  }, [pathDraft, status?.vault_path]);

  useEffect(() => {
    const q = params.get("q");
    if (q) setQuery(q);
  }, [params]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return files;
    return files.filter((file) => file.source.toLowerCase().includes(q));
  }, [files, query]);

  const tree = useMemo(() => buildVaultTree(filtered), [filtered]);
  const directoryPaths = useMemo(() => collectDirectoryPaths(tree), [tree]);

  useEffect(() => {
    if (query.trim()) {
      setExpanded(new Set(directoryPaths));
      return;
    }
    setExpanded((current) => {
      if (current.size > 0) return current;
      return new Set(directoryPaths.filter((path) => !path.includes("/")));
    });
  }, [directoryPaths, query]);

  useEffect(() => {
    setSelectedFile((current) => {
      if (current && filtered.some((file) => file.source === current.source)) return current;
      return filtered[0] ?? null;
    });
  }, [filtered]);

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

  async function saveVaultPath() {
    const nextPath = pathDraft.trim();
    if (!nextPath) {
      setSyncEvent({ kind: "error", text: "Vault 경로를 입력해주세요." });
      return;
    }
    setPathSaving(true);
    setSyncEvent(null);
    try {
      await setVaultPath(nextPath);
      await load();
      setSyncEvent({ kind: "done", result: {}, skipped: [] });
    } catch (e) {
      setSyncEvent({ kind: "error", text: e instanceof Error ? e.message : "Vault 경로 저장에 실패했습니다." });
    } finally {
      setPathSaving(false);
    }
  }

  async function runClear() {
    const confirmation = window.prompt("전체 인덱스를 삭제하려면 CLEAR를 입력하세요.");
    if (confirmation !== "CLEAR") return;
    await clearIndex();
    await load();
  }

  async function openIndexedFile(file: IndexedFile) {
    setSelectedFile(file);
    try {
      await openFile(file.source);
    } catch (e) {
      setSyncEvent({ kind: "error", text: e instanceof Error ? e.message : "파일을 열지 못했습니다." });
    }
  }

  return (
    <>
      <PageHeader
        title="Vault"
        description="인덱싱된 로컬 문서를 디렉토리 구조로 탐색하고 바로 엽니다."
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

      <section className="surface mt-5 rounded-lg p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
          <label className="min-w-0 flex-1">
            <span className="text-sm font-medium">Vault 경로 변경</span>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              로컬 문서가 들어 있는 디렉토리의 절대 경로를 입력하세요. 경로를 바꾼 뒤에는 SYNC를 실행해야 새 문서가 인덱싱됩니다.
            </p>
            <Input
              className="mt-2"
              value={pathDraft}
              onChange={(event) => setPathDraft(event.target.value)}
              placeholder="/Users/me/Documents/vault"
              onKeyDown={(event) => {
                if (event.key === "Enter") void saveVaultPath();
              }}
            />
          </label>
          <Button onClick={() => void saveVaultPath()} disabled={pathSaving}>
            <Save className="size-4" />
            {pathSaving ? "저장 중" : "경로 저장"}
          </Button>
        </div>
      </section>

      {syncEvent ? (
        <section className="surface mt-5 rounded-lg p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-medium">
                {syncEvent.kind === "progress" ? syncEvent.stage : syncEvent.kind === "done" ? "완료" : "오류"}
              </div>
              <div className="mt-1 truncate text-xs text-muted-foreground">
                {syncEvent.kind === "progress"
                  ? syncEvent.file || "작업 대기 중"
                  : syncEvent.kind === "error"
                    ? syncEvent.text
                    : "인덱스가 갱신되었습니다."}
              </div>
            </div>
            {syncEvent.kind === "done" ? <Badge variant="secondary">done</Badge> : null}
          </div>
          <Progress
            className="mt-3"
            value={
              syncEvent.kind === "progress" && typeof syncEvent.fraction === "number"
                ? syncEvent.fraction * 100
                : syncEvent.kind === "done"
                  ? 100
                  : null
            }
          />
        </section>
      ) : null}

      <section className="mt-7 grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="surface overflow-hidden rounded-lg">
          <div className="flex flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full max-w-md">
              <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" />
              <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="파일 검색" className="pl-9" />
            </div>
            <Badge variant="outline">{filtered.length} files</Badge>
          </div>

          {filtered.length === 0 ? (
            <div className="p-6">
              <EmptyState
                title="인덱싱된 파일이 없습니다"
                description="Vault 경로를 설정한 뒤 SYNC를 실행하면 파일 목록이 표시됩니다."
                action={
                  <Button onClick={runSync} disabled={syncDisabled} title={!hasVaultPath ? "Vault 경로를 먼저 설정해주세요." : undefined}>
                    SYNC 실행
                  </Button>
                }
              />
            </div>
          ) : (
            <div className="scrollbar-soft max-h-[620px] overflow-y-auto py-2">
              {tree.children.map((node) => (
                <VaultTreeRow
                  key={node.path}
                  node={node}
                  depth={0}
                  expanded={expanded}
                  selectedSource={selectedFile?.source}
                  onToggle={(path) => toggleExpanded(path, setExpanded)}
                  onOpenFile={(file) => void openIndexedFile(file)}
                />
              ))}
            </div>
          )}
        </div>

        <aside className="space-y-4">
          <section className="surface rounded-lg p-4">
            <div className="flex items-center gap-2">
              <FileText className="size-4 text-primary" />
              <div className="text-sm font-semibold">선택 파일</div>
            </div>
            {selectedFile ? (
              <div className="mt-4 space-y-4">
                <div>
                  <div className="break-words text-sm font-semibold leading-6">{selectedFile.source.split("/").pop()}</div>
                  <div className="mt-1 break-all text-xs leading-5 text-muted-foreground">{selectedFile.source}</div>
                </div>
                <dl className="grid gap-3 text-sm">
                  <MetaRow label="형식" value={selectedFile.doc_type || "-"} />
                  <MetaRow label="크기" value={formatBytes(selectedFile.size)} />
                  <MetaRow label="동기화" value={relativeTime(selectedFile.synced_at)} />
                </dl>
                <Button className="w-full" onClick={() => void openIndexedFile(selectedFile)}>
                  <ExternalLink className="size-4" />
                  파일 열기
                </Button>
              </div>
            ) : (
              <p className="mt-4 text-sm leading-6 text-muted-foreground">
                트리에서 파일을 선택하면 상세 정보가 표시됩니다.
              </p>
            )}
          </section>

          <section className="rounded-lg border border-destructive/30 p-4">
            <div className="flex flex-col gap-3">
              <div>
                <div className="text-sm font-medium">인덱스 초기화</div>
                <div className="text-xs leading-5 text-muted-foreground">Vault 파일은 삭제하지 않고 ChromaDB 인덱스만 비웁니다.</div>
              </div>
              <Button variant="destructive" onClick={runClear}>
                <Trash2 className="size-4" />
                Clear
              </Button>
            </div>
          </section>
        </aside>
      </section>
    </>
  );
}

function VaultTreeRow({
  node,
  depth,
  expanded,
  selectedSource,
  onToggle,
  onOpenFile,
}: {
  node: VaultTreeNode;
  depth: number;
  expanded: Set<string>;
  selectedSource?: string;
  onToggle: (path: string) => void;
  onOpenFile: (file: IndexedFile) => void;
}) {
  const isDirectory = node.type === "directory";
  const isExpanded = expanded.has(node.path);
  const selected = node.file?.source === selectedSource;
  const paddingLeft = 14 + depth * 18;

  if (isDirectory) {
    return (
      <div>
        <button
          type="button"
          aria-expanded={isExpanded}
          onClick={() => onToggle(node.path)}
          className="flex h-9 w-full min-w-0 items-center gap-2 px-3 text-left text-sm hover:bg-secondary/70"
          style={{ paddingLeft }}
        >
          {isExpanded ? <ChevronDown className="size-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="size-4 shrink-0 text-muted-foreground" />}
          {isExpanded ? <FolderOpen className="size-4 shrink-0 text-primary" /> : <Folder className="size-4 shrink-0 text-muted-foreground" />}
          <span className="truncate font-medium">{node.name}</span>
          <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">{countFiles(node)}</span>
        </button>
        {isExpanded
          ? node.children.map((child) => (
              <VaultTreeRow
                key={child.path}
                node={child}
                depth={depth + 1}
                expanded={expanded}
                selectedSource={selectedSource}
                onToggle={onToggle}
                onOpenFile={onOpenFile}
              />
            ))
          : null}
      </div>
    );
  }

  if (!node.file) return null;

  return (
    <button
      type="button"
      onClick={() => onOpenFile(node.file as IndexedFile)}
      className={cn(
        "flex h-9 w-full min-w-0 items-center gap-2 px-3 text-left text-sm hover:bg-secondary/70",
        selected && "bg-secondary text-foreground",
      )}
      style={{ paddingLeft }}
    >
      <FileText className="size-4 shrink-0 text-muted-foreground" />
      <span className="truncate">{node.name}</span>
      <span className="ml-auto hidden shrink-0 text-[11px] text-muted-foreground sm:inline">{formatBytes(node.file.size)}</span>
    </button>
  );
}

function buildVaultTree(files: IndexedFile[]): VaultTreeNode {
  const root: VaultTreeNode = { name: "Vault", path: "", type: "directory", children: [] };
  for (const file of files) {
    const parts = file.source.split("/").filter(Boolean);
    let cursor = root;
    parts.forEach((part, index) => {
      const path = parts.slice(0, index + 1).join("/");
      const isFile = index === parts.length - 1;
      let next = cursor.children.find((child) => child.name === part && child.type === (isFile ? "file" : "directory"));
      if (!next) {
        next = {
          name: part,
          path,
          type: isFile ? "file" : "directory",
          children: [],
          file: isFile ? file : undefined,
        };
        cursor.children.push(next);
      }
      cursor = next;
    });
  }
  sortTree(root);
  return root;
}

function sortTree(node: VaultTreeNode) {
  node.children.sort((a, b) => {
    if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  node.children.forEach(sortTree);
}

function collectDirectoryPaths(root: VaultTreeNode): string[] {
  const out: string[] = [];
  function walk(node: VaultTreeNode) {
    if (node.type === "directory" && node.path) out.push(node.path);
    node.children.forEach(walk);
  }
  walk(root);
  return out;
}

function toggleExpanded(path: string, setExpanded: (value: (current: Set<string>) => Set<string>) => void) {
  setExpanded((current) => {
    const next = new Set(current);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    return next;
  });
}

function countFiles(node: VaultTreeNode): number {
  if (node.type === "file") return 1;
  return node.children.reduce((total, child) => total + countFiles(child), 0);
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b pb-2 last:border-b-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate text-right text-xs font-medium">{value}</dd>
    </div>
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
