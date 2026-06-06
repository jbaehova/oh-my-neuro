import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { BookOpen, FileText, Loader2, RefreshCw, Search, Sparkles } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WikiKnowledgeMap } from "@/components/wiki/WikiKnowledgeMap";
import {
  easyIndexWiki,
  getWikiGraph,
  getWikiLint,
  getWikiPages,
  getWikiStatus,
  openFile,
  rebuildWiki,
  type WikiEasyIndexResponse,
  type WikiGraph,
  type WikiLintIssue,
  type WikiPageSummary,
  type WikiStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export function WikiPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const selectedPage = params.get("page") || "";
  const [status, setStatus] = useState<WikiStatus | null>(null);
  const [pages, setPages] = useState<WikiPageSummary[]>([]);
  const [graph, setGraph] = useState<WikiGraph | null>(null);
  const [issues, setIssues] = useState<WikiLintIssue[]>([]);
  const [query, setQuery] = useState(() => params.get("q") || "");
  const [easyIndex, setEasyIndex] = useState<WikiEasyIndexResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    setLoading(true);
    try {
      const [nextStatus, nextPages, nextGraph, nextIssues] = await Promise.all([
        getWikiStatus(),
        getWikiPages(),
        getWikiGraph(),
        getWikiLint(),
      ]);
      setStatus(nextStatus);
      setPages(nextPages);
      setGraph(nextGraph);
      setIssues(nextIssues);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Wiki 정보를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const highlightedSources = useMemo(
    () => easyIndex?.results.map((item) => item.source) ?? [],
    [easyIndex],
  );
  const sourceByPageId = useMemo(() => {
    const out = new Map<string, string>();
    for (const node of graph?.nodes ?? []) {
      if (node.kind === "source" && node.page_id && node.source_path) {
        out.set(node.page_id, node.source_path);
      }
    }
    return out;
  }, [graph]);

  const okIssue = issues.length === 1 && issues[0]?.code === "ok";

  async function submitSearch(event?: FormEvent) {
    event?.preventDefault();
    const q = query.trim();
    const next = new URLSearchParams(params);
    if (q) next.set("q", q);
    else next.delete("q");
    setParams(next, { replace: true });
    await load();
    if (!q) {
      setEasyIndex(null);
      return;
    }
    setSearching(true);
    try {
      setEasyIndex(await easyIndexWiki(q));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Easy index 검색에 실패했습니다.");
    } finally {
      setSearching(false);
    }
  }

  async function rebuild() {
    setRebuilding(true);
    setError("");
    try {
      await rebuildWiki(true);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Wiki rebuild에 실패했습니다.");
    } finally {
      setRebuilding(false);
    }
  }

  function selectPage(pageId: string) {
    const next = new URLSearchParams(params);
    next.set("page", pageId);
    setParams(next, { replace: true });
  }

  async function openSource(source: string) {
    try {
      await openFile(source);
    } catch {
      navigate(`/vault?q=${encodeURIComponent(source.split("/").pop() || source)}`);
    }
  }

  return (
    <>
      <PageHeader
        title="Wiki"
        description="Vault 문서를 요약한 Markdown 지식 레이어와 원본 문서 관계를 확인합니다."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={status?.enabled ? "secondary" : "warning"}>
              {status?.enabled ? "Wiki ON" : "Wiki OFF"}
            </Badge>
            <Button onClick={() => void rebuild()} disabled={rebuilding}>
              {rebuilding ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
              Rebuild
            </Button>
          </div>
        }
      />

      {error ? (
        <div className="mb-5 rounded-lg border border-destructive/30 bg-destructive/[0.06] px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="상태" value={status?.configured ? "설정됨" : "Vault 필요"} />
        <Metric label="문서" value={`${status?.document_count ?? status?.source_count ?? 0}`} />
        <Metric label="생성 페이지" value={`${status?.generated_page_count ?? status?.page_count ?? pages.length}`} />
        <Metric label="위키 청크" value={`${status?.indexed_chunks ?? 0}`} />
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6">
          <form onSubmit={submitSearch} className="surface rounded-lg p-4">
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  className="pl-9"
                  placeholder="Wiki와 원본 문서를 함께 검색"
                />
              </div>
              <Button type="submit" disabled={loading || searching}>
                {searching ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
                Easy index
              </Button>
            </div>
          </form>

          {easyIndex ? (
            <section className="surface rounded-lg p-4">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold">Easy index 결과</h2>
                <Badge variant={easyIndex.semantic_available ? "secondary" : "warning"}>
                  {easyIndex.results.length} sources
                </Badge>
              </div>
              {easyIndex.error || !easyIndex.semantic_available ? (
                <p className="mt-3 rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-xs text-foreground">
                  {easyIndex.error || "Semantic index를 사용할 수 없습니다."}
                </p>
              ) : null}
              {easyIndex.results.length > 0 ? (
                <div className="mt-3 space-y-2">
                  {easyIndex.results.map((result) => (
                    <button
                      key={result.source}
                      type="button"
                      onClick={() => void openSource(result.source)}
                      className="block w-full rounded-md border px-3 py-2 text-left transition hover:bg-secondary/50"
                    >
                      <div className="flex min-w-0 items-center justify-between gap-3">
                        <span className="truncate text-sm font-medium">{result.title}</span>
                        <Badge variant="outline">{result.score.toFixed(2)}</Badge>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                        {cleanExcerpt(result.excerpt) || result.source}
                      </p>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="mt-3 rounded-md border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">
                  검색 결과가 없습니다.
                </div>
              )}
            </section>
          ) : null}

          {loading ? (
            <div className="grid min-h-[360px] place-items-center text-sm text-muted-foreground">
              <div className="flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" />
                Wiki 불러오는 중
              </div>
            </div>
          ) : pages.length === 0 ? (
            <EmptyState
              title="생성된 Wiki 페이지가 없습니다"
              description="Vault를 동기화한 뒤 Rebuild를 실행하면 문서 노트와 개념 페이지가 생성됩니다."
              action={
                <Button onClick={() => void rebuild()} disabled={rebuilding}>
                  Rebuild 실행
                </Button>
              }
            />
          ) : (
            <section className="grid gap-3 md:grid-cols-2">
              {pages.map((page) => (
                <button
                  key={page.id}
                  type="button"
                  onClick={() => {
                    const source = sourceByPageId.get(page.id);
                    if (source) {
                      void openSource(source);
                      return;
                    }
                    selectPage(page.id);
                    navigate(`/wiki/detail?page=${encodeURIComponent(page.id)}`);
                  }}
                  className={cn(
                    "surface min-w-0 rounded-lg border p-4 text-left transition hover:border-primary/30",
                    selectedPage === page.id && "border-primary/50 bg-secondary/40",
                  )}
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <BookOpen className="size-4 shrink-0 text-muted-foreground" />
                        <h2 className="truncate text-sm font-semibold">{page.title}</h2>
                      </div>
                      <p className="mt-1 truncate text-xs text-muted-foreground">{page.path}</p>
                    </div>
                    <Badge variant="outline">{sectionLabel(page.section)}</Badge>
                  </div>
                  <p className="mt-3 line-clamp-3 text-sm leading-6 text-muted-foreground">
                    {cleanExcerpt(page.excerpt) || "요약 없음"}
                  </p>
                </button>
              ))}
            </section>
          )}
        </div>

        <aside className="space-y-6">
          <WikiKnowledgeMap
            graph={graph}
            selectedPageId={selectedPage}
            highlightedSources={highlightedSources}
            onSelectPage={(pageId) => {
              selectPage(pageId);
              navigate(`/wiki/detail?page=${encodeURIComponent(pageId)}`);
            }}
            onOpenSource={(source) => void openSource(source)}
          />

          <section className="surface rounded-lg p-4">
            <div className="flex items-center gap-2">
              <FileText className="size-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold">검사 결과</h2>
            </div>
            <div className="mt-3 space-y-2">
              {okIssue ? (
                <p className="text-sm text-muted-foreground">Wiki lint issue가 없습니다.</p>
              ) : (
                issues.map((issue) => (
                  <div key={`${issue.code}-${issue.page}-${issue.message}`} className="rounded-md border px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium">{issue.code}</span>
                      <Badge variant={issue.severity === "error" ? "warning" : "outline"}>{issue.severity}</Badge>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">{issue.message}</p>
                  </div>
                ))
              )}
            </div>
          </section>
        </aside>
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

function sectionLabel(section: string) {
  if (section === "sources") return "문서";
  if (section === "concepts") return "개념";
  if (section === "root") return "요약";
  return section || "wiki";
}

function cleanExcerpt(value?: string) {
  if (!value) return "";
  return value
    .replace(/Generated at:\s*\S+/gi, "")
    .replace(/^#+\s*/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}
