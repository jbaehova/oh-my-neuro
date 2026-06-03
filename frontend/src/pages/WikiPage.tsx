import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, BookOpen, FileText, RefreshCw, Search } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getWikiLint, getWikiPage, getWikiPages, getWikiStatus, rebuildWiki, WikiLintIssue, WikiPageContent, WikiPageSummary, WikiStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

type LoadOptions = {
  selectFirst?: boolean;
};

export function WikiPage() {
  const [status, setStatus] = useState<WikiStatus | null>(null);
  const [pages, setPages] = useState<WikiPageSummary[]>([]);
  const [selected, setSelected] = useState<WikiPageContent | null>(null);
  const [issues, setIssues] = useState<WikiLintIssue[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);
  const [error, setError] = useState("");

  async function load(nextQuery = query, options: LoadOptions = {}) {
    setLoading(true);
    setError("");
    try {
      const [nextStatus, nextPages, nextIssues] = await Promise.all([
        getWikiStatus(),
        getWikiPages(nextQuery),
        getWikiLint(),
      ]);
      setStatus(nextStatus);
      setPages(nextPages);
      setIssues(nextIssues);
      if ((options.selectFirst || !selected) && nextPages[0]) {
        const first = await getWikiPage(nextPages[0].id);
        setSelected(first);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Wiki를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("", { selectFirst: true });
    // Initial load only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function search() {
    setSelected(null);
    await load(query, { selectFirst: true });
  }

  async function choose(page: WikiPageSummary) {
    setSelected(await getWikiPage(page.id));
  }

  async function rebuild() {
    setRebuilding(true);
    setError("");
    try {
      await rebuildWiki();
      setSelected(null);
      await load(query, { selectFirst: true });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Wiki 재생성에 실패했습니다.");
    } finally {
      setRebuilding(false);
    }
  }

  const warningCount = useMemo(() => issues.filter((issue) => issue.severity !== "info").length, [issues]);

  return (
    <>
      <PageHeader
        title="Wiki"
        description="Vault 문서를 LLM이 정리한 Markdown 지식 레이어입니다."
        action={
          <Button onClick={rebuild} disabled={rebuilding || !status?.configured || !status?.enabled}>
            <RefreshCw className={rebuilding ? "size-4 animate-spin" : "size-4"} />
            Rebuild
          </Button>
        }
      />

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="상태" value={status?.enabled ? "활성" : "비활성"} />
        <Metric label="페이지" value={`${status?.page_count ?? 0}`} />
        <Metric label="소스" value={`${status?.source_count ?? 0}`} />
        <Metric label="마지막 빌드" value={relativeTime(status?.last_built_at)} />
      </section>

      {error && (
        <section className="mt-5 rounded-lg border border-destructive/30 p-4 text-sm text-destructive">
          {error}
        </section>
      )}

      {status?.error && (
        <section className="mt-5 flex items-center gap-2 rounded-lg border border-amber-400/40 p-4 text-sm">
          <AlertTriangle className="size-4 text-amber-500" />
          <span>{status.error}</span>
        </section>
      )}

      <div className="mt-7 grid gap-5 lg:grid-cols-[320px_1fr]">
        <aside className="space-y-4">
          <div className="surface rounded-lg p-3">
            <div className="flex gap-2">
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void search();
                  }}
                  placeholder="Wiki 검색"
                  className="pl-9"
                />
              </div>
              <Button variant="outline" size="icon" onClick={search}>
                <Search className="size-4" />
              </Button>
            </div>
          </div>

          <div className="overflow-hidden rounded-lg border">
            <div className="flex items-center justify-between border-b bg-secondary px-3 py-2">
              <div className="text-xs font-medium text-muted-foreground">Pages</div>
              <Badge variant="outline">{pages.length}</Badge>
            </div>
            <div className="max-h-[520px] overflow-y-auto">
              {loading ? (
                <div className="p-3 text-sm text-muted-foreground">Loading</div>
              ) : pages.length === 0 ? (
                <div className="p-3 text-sm text-muted-foreground">Wiki 페이지가 없습니다.</div>
              ) : (
                pages.map((page) => (
                  <button
                    key={page.id}
                    type="button"
                    onClick={() => void choose(page)}
                    className={cn(
                      "block w-full border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-secondary",
                      selected?.id === page.id && "bg-secondary",
                    )}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <FileText className="size-4 shrink-0 text-muted-foreground" />
                      <span className="truncate font-medium">{page.title}</span>
                    </div>
                    <div className="mt-1 truncate text-xs text-muted-foreground">{page.path}</div>
                  </button>
                ))
              )}
            </div>
          </div>

          <div className="rounded-lg border p-3">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-xs font-medium text-muted-foreground">Lint</div>
              <Badge variant={warningCount ? "warning" : "secondary"}>{warningCount ? `${warningCount} issues` : "OK"}</Badge>
            </div>
            <div className="space-y-2">
              {issues.slice(0, 5).map((issue) => (
                <div key={`${issue.code}-${issue.page || ""}`} className="text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{issue.code}</span>: {issue.message}
                </div>
              ))}
            </div>
          </div>
        </aside>

        <section className="min-w-0 rounded-lg border bg-background">
          {selected ? (
            <>
              <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
                <div className="min-w-0">
                  <div className="truncate text-base font-semibold">{selected.title}</div>
                  <div className="truncate text-xs text-muted-foreground">{selected.path}</div>
                </div>
                <Badge variant="secondary">{selected.section}</Badge>
              </div>
              <article className="prose prose-sm max-w-none p-4 dark:prose-invert">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{selected.content}</ReactMarkdown>
              </article>
            </>
          ) : (
            <div className="grid min-h-[420px] place-items-center p-8 text-center">
              <div>
                <BookOpen className="mx-auto size-8 text-muted-foreground" />
                <div className="mt-3 text-sm font-medium">Wiki page를 선택하세요</div>
                <div className="mt-1 text-xs text-muted-foreground">Rebuild 후 생성된 Markdown 지식 페이지를 확인할 수 있습니다.</div>
              </div>
            </div>
          )}
        </section>
      </div>
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
