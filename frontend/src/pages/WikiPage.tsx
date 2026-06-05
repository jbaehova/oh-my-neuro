import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, BookOpen, FileText, Loader2, RefreshCw, Search } from "lucide-react";

import { WikiContentViewer } from "@/components/wiki/WikiContentViewer";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getWikiLint,
  getWikiPage,
  getWikiPages,
  getWikiStatus,
  rebuildWiki,
  WikiLintIssue,
  WikiPageContent,
  WikiPageSummary,
  WikiStatus,
} from "@/lib/api";
import {
  buildTopicChatParams,
  buildWikiArticleModel,
  buildWikiDisplayModel,
  cleanWikiExcerpt,
  getTopicSummary,
  parseWikiContent,
  relativeTimeFromIso,
  topicParamsToSearch,
} from "@/lib/wikiContent";
import { newSessionId } from "@/hooks/useSessions";
import { cn } from "@/lib/utils";

type LoadOptions = {
  selectFirst?: boolean;
  pageId?: string | null;
};

export function WikiPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState<WikiStatus | null>(null);
  const [pages, setPages] = useState<WikiPageSummary[]>([]);
  const [selected, setSelected] = useState<WikiPageContent | null>(null);
  const [issues, setIssues] = useState<WikiLintIssue[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [pageLoading, setPageLoading] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [error, setError] = useState("");

  const documentPages = useMemo(
    () => pages.filter((page) => page.section === "sources"),
    [pages],
  );

  const filteredPages = documentPages;

  const contradictionConcepts = useMemo(
    () =>
      issues
        .filter((issue) => issue.code === "contradiction")
        .map((issue) => String(issue.metadata?.concept || ""))
        .filter(Boolean),
    [issues],
  );

  const selectedTopic = useMemo(() => {
    if (!selected) return null;
    const parsed = parseWikiContent(selected.content);
    const article = buildWikiArticleModel(parsed, selected.title, selected.linked_source_pages ?? []);
    const summarySection = parsed.sections.find((section) => section.normalized === "summary");
    const sourceNotesSection = parsed.sections.find((section) => section.normalized === "source notes");
    const display = buildWikiDisplayModel(parsed, summarySection, sourceNotesSection);
    return {
      parsed,
      display,
      summary: article.introLine || getTopicSummary(parsed, display),
    };
  }, [selected]);

  const choose = useCallback(async (page: WikiPageSummary | string) => {
    const pageId = typeof page === "string" ? page : page.id;
    setPageLoading(true);
    setError("");
    try {
      const content = await getWikiPage(pageId);
      setSelected(content);
      setParams({ page: pageId }, { replace: true });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Wiki 페이지를 불러오지 못했습니다.");
    } finally {
      setPageLoading(false);
    }
  }, [setParams]);

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

      const targetId = options.pageId ?? params.get("page");
      if (targetId) {
        const found = nextPages.find((p) => p.id === targetId);
        if (found || targetId) {
          await choose(targetId);
          return;
        }
      }
      if ((options.selectFirst || !selected) && nextPages.length > 0) {
        const preferred = nextPages.find((page) => page.section === "sources") ?? nextPages[0];
        await choose(preferred.id);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Wiki를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("", { selectFirst: !params.get("page"), pageId: params.get("page") });
    // Initial load only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function search() {
    setSelected(null);
    await load(query, { selectFirst: true });
  }

  async function rebuild() {
    setRebuilding(true);
    setError("");
    try {
      const result = await rebuildWiki(true);
      if (result.sources_processed === 0 && result.pages_written === 0) {
        setError("Rebuild가 완료됐지만 생성된 페이지가 없습니다. Vault 경로와 OPENAI_API_KEY를 확인해주세요.");
      }
      setSelected(null);
      await load(query, { selectFirst: true });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Wiki 재생성에 실패했습니다.");
    } finally {
      setRebuilding(false);
    }
  }

  function askAboutTopic() {
    if (!selected || !selectedTopic) return;
    const session = newSessionId();
    const topicSearch = topicParamsToSearch(buildTopicChatParams(selected, selectedTopic.summary));
    navigate(`/chat?session=${session}&${topicSearch}`);
  }

  function askWithQuestion(question: string) {
    if (!selected || !selectedTopic) return;
    const session = newSessionId();
    const topicSearch = topicParamsToSearch(buildTopicChatParams(selected, selectedTopic.summary));
    navigate(`/chat?session=${session}&${topicSearch}&prompt=${encodeURIComponent(question)}`);
  }

  function learnMoreAboutTopic() {
    if (!selected) return;
    navigate(`/wiki/detail?page=${encodeURIComponent(selected.id)}`);
  }

  const warningCount = useMemo(() => issues.filter((issue) => issue.severity !== "info" && issue.code !== "ok").length, [issues]);

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
        <Metric label="마지막 빌드" value={relativeTimeFromIso(status?.last_built_at)} />
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
              <div className="text-xs font-medium text-muted-foreground">문서 노트</div>
              <Badge variant="outline">{filteredPages.length}</Badge>
            </div>
            <div className="max-h-[520px] overflow-y-auto">
              {loading ? (
                <div className="p-3 text-sm text-muted-foreground">Loading</div>
              ) : filteredPages.length === 0 ? (
                <div className="p-3 text-sm text-muted-foreground">Wiki 페이지가 없습니다.</div>
              ) : (
                filteredPages.map((page) => (
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
                    <div className="mt-1 truncate text-xs text-muted-foreground">
                      {cleanWikiExcerpt(page.excerpt) || page.path}
                    </div>
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
                <div key={`${issue.code}-${issue.page || ""}-${issue.message}`} className="text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{issue.code}</span>: {issue.message}
                </div>
              ))}
            </div>
          </div>
        </aside>

        <section className="flex min-w-0 flex-col overflow-hidden rounded-xl border bg-muted/20">
          {selected ? (
            <div className="scrollbar-soft max-h-[calc(100vh-220px)] flex-1 overflow-y-auto">
              {pageLoading ? (
                <WikiContentSkeleton />
              ) : (
                <WikiContentViewer
                  content={selected.content}
                  pageTitle={selected.title}
                  pagePath={selected.path}
                  section={selected.section}
                  updatedAt={selected.updated_at}
                  linkedSourcePages={selected.linked_source_pages ?? []}
                  contradictionConcepts={contradictionConcepts}
                  onNavigatePage={(pageId) => void choose(pageId)}
                  onAskTopic={askAboutTopic}
                  onAskWithQuestion={askWithQuestion}
                  onLearnMore={learnMoreAboutTopic}
                />
              )}
            </div>
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

function WikiContentSkeleton() {
  return (
    <div className="space-y-5 p-5 sm:p-6">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        페이지 불러오는 중
      </div>
      <div className="animate-pulse rounded-2xl border bg-muted/30 p-7">
        <div className="h-3 w-16 rounded bg-muted" />
        <div className="mt-4 h-7 w-2/3 rounded bg-muted" />
        <div className="mt-3 h-4 w-full rounded bg-muted" />
      </div>
      {[0, 1].map((i) => (
        <div key={i} className="animate-pulse rounded-2xl border p-5">
          <div className="flex gap-4">
            <div className="size-9 rounded-xl bg-muted" />
            <div className="flex-1 space-y-2">
              <div className="h-3 w-full rounded bg-muted" />
              <div className="h-3 w-4/5 rounded bg-muted" />
            </div>
          </div>
        </div>
      ))}
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
