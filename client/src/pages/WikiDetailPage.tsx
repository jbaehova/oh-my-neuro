import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";

import { WikiContentViewer } from "@/components/wiki/WikiContentViewer";
import { Button } from "@/components/ui/button";
import { getWikiPage, WikiPageContent } from "@/lib/api";
import { newSessionId } from "@/hooks/useSessions";
import {
  buildTopicChatParams,
  buildWikiArticleModel,
  buildWikiDisplayModel,
  getTopicSummary,
  parseWikiContent,
  topicParamsToSearch,
} from "@/lib/wikiContent";

export function WikiDetailPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const pageId = params.get("page") || "";
  const [page, setPage] = useState<WikiPageContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!pageId) {
      setError("Wiki page가 지정되지 않았습니다.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    void getWikiPage(pageId)
      .then(setPage)
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Wiki 상세 페이지를 불러오지 못했습니다."))
      .finally(() => setLoading(false));
  }, [pageId]);

  const topicSummary = useMemo(() => {
    if (!page) return "";
    const parsed = parseWikiContent(page.content);
    const article = buildWikiArticleModel(parsed, page.title, page.linked_source_pages ?? []);
    const summarySection = parsed.sections.find((section) => section.normalized === "summary");
    const sourceNotesSection = parsed.sections.find((section) => section.normalized === "source notes");
    const display = buildWikiDisplayModel(parsed, summarySection, sourceNotesSection);
    return article.introLine || getTopicSummary(parsed, display);
  }, [page]);

  const choosePage = useCallback(
    (nextPageId: string) => {
      navigate(`/wiki/detail?page=${encodeURIComponent(nextPageId)}`);
    },
    [navigate],
  );

  function askAboutTopic() {
    if (!page) return;
    const session = newSessionId();
    const topicSearch = topicParamsToSearch(buildTopicChatParams(page, topicSummary));
    navigate(`/chat?session=${session}&${topicSearch}`);
  }

  function askWithQuestion(question: string) {
    if (!page) return;
    const session = newSessionId();
    const topicSearch = topicParamsToSearch(buildTopicChatParams(page, topicSummary));
    navigate(`/chat?session=${session}&${topicSearch}&prompt=${encodeURIComponent(question)}`);
  }

  if (loading) {
    return (
      <div className="grid min-h-[420px] place-items-center text-sm text-muted-foreground">
        <div className="flex items-center gap-2">
          <Loader2 className="size-4 animate-spin" />
          상세 정리 불러오는 중
        </div>
      </div>
    );
  }

  if (error || !page) {
    return (
      <div className="rounded-lg border border-destructive/30 p-4 text-sm text-destructive">
        {error || "Wiki 상세 페이지를 표시할 수 없습니다."}
      </div>
    );
  }

  return (
    <div className="wiki-detail-shell">
      <div className="mb-4 px-4 sm:px-8">
        <Button variant="outline" size="sm" className="gap-1.5 rounded-md" onClick={() => navigate(`/wiki?page=${encodeURIComponent(page.id)}`)}>
          <ArrowLeft className="size-4" />
          Wiki로 돌아가기
        </Button>
      </div>
      <WikiContentViewer
        content={page.content}
        pageTitle={page.title}
        pagePath={page.path}
        section={page.section}
        updatedAt={page.updated_at}
        linkedSourcePages={page.linked_source_pages ?? []}
        onNavigatePage={choosePage}
        onAskTopic={askAboutTopic}
        onAskWithQuestion={askWithQuestion}
      />
    </div>
  );
}
