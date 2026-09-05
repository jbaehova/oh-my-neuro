import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  ChevronRight,
  FileText,
  HelpCircle,
  Link2,
  ShieldCheck,
} from "lucide-react";

import { MarkdownContent } from "@/components/MarkdownContent";
import { Button } from "@/components/ui/button";
import {
  buildWikiArticleModel,
  findWikiSection,
  isKnownSection,
  parseConceptItem,
  parseWikiContent,
  parseWikiLinks,
  relativeTimeFromIso,
  replaceWikiLinksWithMarkdown,
  sectionHeadingKo,
  sectionLabelKo,
  type WikiNoteSection,
  type WikiDocumentMeta,
  type WikiSection,
} from "@/lib/wikiContent";
import { openFile } from "@/lib/api";
import { cn } from "@/lib/utils";

type WikiContentViewerProps = {
  content: string;
  pageTitle: string;
  pagePath: string;
  section: string;
  updatedAt?: string;
  linkedSourcePages?: string[];
  contradictionConcepts?: string[];
  onNavigatePage: (pageId: string) => void;
  onAskTopic?: () => void;
  onAskWithQuestion?: (question: string) => void;
  onLearnMore?: () => void;
};

export function WikiContentViewer({
  content,
  pageTitle,
  pagePath,
  section,
  updatedAt,
  linkedSourcePages = [],
  contradictionConcepts = [],
  onNavigatePage,
  onAskTopic,
  onAskWithQuestion,
  onLearnMore,
}: WikiContentViewerProps) {
  const navigate = useNavigate();
  const parsed = useMemo(() => parseWikiContent(content), [content]);
  const article = useMemo(
    () => buildWikiArticleModel(parsed, pageTitle, linkedSourcePages),
    [parsed, pageTitle, linkedSourcePages],
  );

  const hasContradiction = contradictionConcepts.some(
    (concept) => pageTitle.toLowerCase() === concept.toLowerCase() || pagePath.includes(concept),
  );
  const verification = findWikiSection(parsed, "verification");
  const conceptsSection = findWikiSection(parsed, "concepts");
  const sourceAnchorsSection = findWikiSection(parsed, "source anchors");
  const otherSections = parsed.sections.filter(
    (sec) =>
      ![
        "summary",
        "topic overview",
        "background",
        "main content",
        "practical notes",
        "open questions",
        "source documents",
        "source notes",
        "verification",
        "concepts",
        "source anchors",
      ].includes(sec.normalized) &&
      isKnownSection(sec),
  );

  async function openVault(source: string) {
    try {
      await openFile(source);
    } catch {
      const filename = source.split("/").pop() || source;
      navigate(`/vault?q=${encodeURIComponent(filename)}`);
    }
  }

  function askQuestion(question: string) {
    if (onAskWithQuestion) {
      onAskWithQuestion(question);
      return;
    }
    onAskTopic?.();
  }

  const hasDisplayableContent = article.noteSections.length > 0 || article.hasBody;

  return (
    <article className="wiki-article mx-auto max-w-3xl px-4 py-6 sm:px-8 sm:py-8">
      <header className="wiki-article-header border-b pb-6">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="rounded-md bg-muted px-2 py-0.5 font-medium">{sectionLabelKo(section)}</span>
          {updatedAt ? <span>업데이트 {relativeTimeFromIso(updatedAt)}</span> : null}
          {parsed.generatedAt && !updatedAt ? (
            <span>생성 {relativeTimeFromIso(parsed.generatedAt)}</span>
          ) : null}
        </div>
        <h1 className="mt-3 text-2xl font-semibold leading-tight tracking-tight sm:text-[1.75rem]">{pageTitle}</h1>
        {(onAskTopic || onLearnMore) ? (
          <div className="wiki-action-row mt-5">
            {onAskTopic ? (
              <Button size="sm" className="gap-1.5 rounded-md px-4" onClick={onAskTopic}>
                이 주제로 질문
                <ArrowRight className="size-3.5" />
              </Button>
            ) : null}
            {onLearnMore ? (
              <Button variant="outline" size="sm" className="rounded-md px-4" onClick={onLearnMore}>
                더 알아보기
              </Button>
            ) : null}
          </div>
        ) : null}
      </header>

      {hasContradiction ? (
        <div className="wiki-alert-subtle mt-5 flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <p>모순 가능성이 탐지된 개념입니다. 원본 문서와 대조해 확인하세요.</p>
        </div>
      ) : null}

      {article.documentMeta ? (
        <DocumentMetaPanel meta={article.documentMeta} />
      ) : null}

      {article.sources.length > 0 ? (
        <section className="wiki-article-section mt-8">
          <SectionHeading icon={FileText} title="근거 문서" />
          <div className="mt-3 space-y-2">
            {article.sources.map((src, index) => (
              <div
                key={src.source}
                className="wiki-source-card flex flex-col gap-2 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <FileText className="size-4 shrink-0 text-muted-foreground" />
                    <span className="truncate text-sm font-medium">{src.filename}</span>
                  </div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">{src.source}</p>
                  {src.showDescription ? (
                    <p className="mt-2 text-sm leading-6 text-foreground/85">{src.description}</p>
                  ) : null}
                </div>
                <div className="flex shrink-0 flex-wrap gap-2">
                  {article.linkedSourcePages[index] && section === "concepts" ? (
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-md"
                      onClick={() => onNavigatePage(article.linkedSourcePages[index])}
                    >
                      원본 문서 노트
                    </Button>
                  ) : null}
                  <Button variant="outline" size="sm" className="rounded-md" onClick={() => void openVault(src.source)}>
                    파일 열기
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {!hasDisplayableContent ? (
        <section className="wiki-empty-state mt-8 rounded-lg border border-dashed px-5 py-8 text-center">
          <BookOpen className="mx-auto size-8 text-muted-foreground/70" />
          <p className="mt-3 text-sm font-medium">주제 정리가 아직 생성되지 않았습니다.</p>
          <p className="mt-1 text-sm text-muted-foreground">Rebuild를 실행하면 Vault 문서 기반 정리 노트가 생성됩니다.</p>
        </section>
      ) : (
        <section className="wiki-note-sheet mt-8">
          <SectionHeading icon={BookOpen} title="주제 정리" />
          <div className="wiki-note-sheet-body mt-4 space-y-6">
            {article.noteSections.map((noteSection) => (
              <NoteSubsection key={noteSection.key} section={noteSection} onNavigatePage={onNavigatePage} />
            ))}
          </div>
        </section>
      )}

      {conceptsSection && conceptsSection.items.length > 0 ? (
        <section className="wiki-article-section mt-8">
          <SectionHeading icon={Link2} title="관련 개념" count={conceptsSection.items.length} />
          <div className="mt-3 flex flex-wrap gap-2">
            {conceptsSection.items.map((item) => {
              const concept = parseConceptItem(item);
              const links = parseWikiLinks(item);
              return (
                <button
                  key={item}
                  type="button"
                  onClick={() => links[0] && onNavigatePage(links[0].pageId)}
                  className="wiki-source-pill inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-sm transition hover:border-primary/40 hover:text-primary"
                >
                  <span className="font-medium">{concept.name}</span>
                  <ChevronRight className="size-3.5 text-muted-foreground" />
                </button>
              );
            })}
          </div>
        </section>
      ) : null}

      {otherSections.map((sec) => renderMiscSection(sec))}

      {sourceAnchorsSection && sourceAnchorsSection.items.length > 0 ? (
        <section className="wiki-article-section mt-8">
          <SectionHeading icon={BookOpen} title={sectionHeadingKo(sourceAnchorsSection.heading)} />
          <div className="mt-3 flex flex-wrap gap-2">
            {sourceAnchorsSection.items.map((item) => (
              <span key={item} className="mono rounded-md border bg-muted/30 px-2.5 py-1 text-[11px] text-muted-foreground">
                {item}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {article.recommendedQuestions.length > 0 ? (
        <section className="wiki-article-section mt-10 border-t pt-8">
          <SectionHeading icon={HelpCircle} title="추천 질문" />
          <div className="mt-3 flex flex-col gap-2">
            {article.recommendedQuestions.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => askQuestion(question)}
                className="wiki-question-chip rounded-lg border px-4 py-3 text-left text-sm leading-6 transition hover:border-primary/30 hover:bg-muted/40"
              >
                {question}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {verification ? (
        <aside className="wiki-verify-subtle mt-8 flex gap-2 rounded-lg px-3 py-2.5 text-xs leading-5 text-muted-foreground">
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0" />
          <div>
            {verification.items.map((item) => (
              <p key={item}>{item}</p>
            ))}
          </div>
        </aside>
      ) : null}

      <footer className="mt-6 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground/60">
        <span className="mono">{pagePath}</span>
        {parsed.sourceMeta.source ? <span>· {parsed.sourceMeta.source}</span> : null}
      </footer>
    </article>
  );

  function renderMiscSection(section: WikiSection) {
    if (section.normalized === "detected contradictions") {
      return (
        <section key={section.heading} className="wiki-article-section mt-8">
          <SectionHeading icon={AlertTriangle} title={sectionHeadingKo(section.heading)} />
          <BulletList items={section.items} onNavigatePage={onNavigatePage} variant="warning" />
        </section>
      );
    }

    if (section.normalized === "sources" || section.normalized === "maintenance") {
      return (
        <section key={section.heading} className="wiki-article-section mt-8">
          <SectionHeading icon={FileText} title={sectionHeadingKo(section.heading)} />
          <div className="mt-3 space-y-2">
            {section.items.map((item) => {
              const links = parseWikiLinks(item);
              if (links[0]) {
                return (
                  <button
                    key={item}
                    type="button"
                    onClick={() => onNavigatePage(links[0].pageId)}
                    className="flex w-full items-center justify-between rounded-lg border px-4 py-2.5 text-left text-sm transition hover:border-primary/30 hover:text-primary"
                  >
                    {links[0].label}
                    <ChevronRight className="size-4 text-muted-foreground" />
                  </button>
                );
              }
              return (
                <p key={item} className="rounded-lg border px-4 py-2.5 text-sm text-muted-foreground">
                  {item}
                </p>
              );
            })}
          </div>
        </section>
      );
    }

    return (
      <section key={section.heading} className="wiki-article-section mt-8">
        <SectionHeading icon={BookOpen} title={sectionHeadingKo(section.heading)} />
        <div className="wiki-prose mt-3">
          <MarkdownContent
            content={replaceWikiLinksWithMarkdown(section.body)}
            onWikiLink={onNavigatePage}
          />
        </div>
      </section>
    );
  }
}

function SectionHeading({
  icon: Icon,
  title,
  count,
}: {
  icon: typeof BookOpen;
  title: string;
  count?: number;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="size-4 text-muted-foreground" />
      <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
      {typeof count === "number" ? (
        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">{count}</span>
      ) : null}
    </div>
  );
}

function NoteSubsection({
  section,
  onNavigatePage,
}: {
  section: WikiNoteSection;
  onNavigatePage: (pageId: string) => void;
}) {
  const isOverview = section.key === "topic overview";
  const isMainContent = section.key === "main content";
  const isWarning = section.key === "practical notes";

  return (
    <div
      className={cn(
        "wiki-note-block rounded-xl border px-4 py-4 sm:px-5 sm:py-5",
        isOverview && "wiki-note-block-overview",
        isMainContent && "wiki-note-block-main",
        isWarning && "wiki-note-block-warning",
      )}
    >
      <h3 className="text-[13px] font-semibold tracking-tight text-foreground">{section.title}</h3>
      {section.prose ? (
        <div className="wiki-prose mt-3 text-[15px] leading-8 text-foreground/90">
          <MarkdownContent
            content={replaceWikiLinksWithMarkdown(section.prose)}
            onWikiLink={onNavigatePage}
          />
        </div>
      ) : null}
      {section.items.length > 0 ? (
        <BulletList
          items={section.items}
          onNavigatePage={onNavigatePage}
          variant={isWarning ? "warning" : isMainContent ? "main" : undefined}
          className={section.prose ? "mt-3" : "mt-3"}
        />
      ) : null}
    </div>
  );
}

function DocumentMetaPanel({ meta }: { meta: WikiDocumentMeta }) {
  const fields = [
    { label: "문서명", value: meta.documentTitle },
    { label: "문서번호", value: meta.documentNumber },
    { label: "작성일", value: meta.writtenAt },
    { label: "담당", value: meta.author },
    { label: "사건 코드", value: meta.caseCode },
  ].filter((field) => field.value);

  if (fields.length === 0 && !meta.disclaimer) return null;

  return (
    <section className="wiki-doc-meta mt-6 rounded-xl border bg-background/80 px-4 py-4 sm:px-5 sm:py-5">
      {fields.length > 0 ? (
        <dl className="wiki-doc-meta-grid grid gap-x-6 gap-y-3 sm:grid-cols-2">
          {fields.map((field) => (
            <div key={field.label} className="min-w-0">
              <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{field.label}</dt>
              <dd className="mt-1 text-sm font-medium leading-6 text-foreground">{field.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {meta.disclaimer ? (
        <p className="mt-3 rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-xs leading-5 text-muted-foreground">
          {meta.disclaimer}
        </p>
      ) : null}
    </section>
  );
}

function BulletList({
  items,
  onNavigatePage,
  variant,
  className,
}: {
  items: string[];
  onNavigatePage: (pageId: string) => void;
  variant?: "warning" | "main";
  className?: string;
}) {
  return (
    <ul className={cn(
      "wiki-bullet-list space-y-2.5",
      variant === "warning" && "wiki-bullet-list-warning",
      variant === "main" && "wiki-bullet-list-main",
      className,
    )}>
      {items.map((item) => (
        <li key={item} className="flex gap-2.5 text-[15px] leading-7 text-foreground/90">
          <span className="mt-2 size-1.5 shrink-0 rounded-full bg-muted-foreground/50" />
          <div className="min-w-0 flex-1">
            <MarkdownContent content={replaceWikiLinksWithMarkdown(item)} onWikiLink={onNavigatePage} inline />
          </div>
        </li>
      ))}
    </ul>
  );
}
