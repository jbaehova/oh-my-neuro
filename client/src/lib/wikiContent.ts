export type WikiLink = {
  pageId: string;
  label: string;
};

export type WikiSection = {
  heading: string;
  normalized: string;
  body: string;
  items: string[];
};

export type WikiParsedContent = {
  title: string;
  generatedAt: string | null;
  sourceMeta: Record<string, string>;
  sections: WikiSection[];
  preamble: string;
  excerpt: string;
};

const KNOWN_SECTIONS = new Set([
  "summary",
  "background",
  "main content",
  "topic overview",
  "practical notes",
  "open questions",
  "source documents",
  "key facts",
  "concepts",
  "source notes",
  "source anchors",
  "verification",
  "detected contradictions",
  "sources",
  "maintenance",
]);

const SECTION_ALIASES: Record<string, string> = {
  summary: "summary",
  "핵심 요약": "summary",
  background: "background",
  "관련 배경": "background",
  "main content": "main content",
  "주요 내용": "main content",
  "핵심 내용": "main content",
  "key facts": "main content",
  "topic overview": "topic overview",
  "주제 정리": "topic overview",
  "practical notes": "practical notes",
  "실무상 주의할 점": "practical notes",
  "open questions": "open questions",
  "확인해야 할 질문": "open questions",
  "source documents": "source documents",
  "근거 문서": "source documents",
  "source notes": "source notes",
  concepts: "concepts",
  "source anchors": "source anchors",
  verification: "verification",
  "detected contradictions": "detected contradictions",
  sources: "sources",
  maintenance: "maintenance",
};

export function normalizeSectionHeading(heading: string): string {
  const trimmed = heading.trim();
  if (SECTION_ALIASES[trimmed]) return SECTION_ALIASES[trimmed];
  const lower = trimmed.toLowerCase();
  return SECTION_ALIASES[lower] || lower;
}

export function sectionLabelKo(section: string): string {
  const map: Record<string, string> = {
    concepts: "개념",
    sources: "문서 노트",
    root: "인덱스",
  };
  return map[section] || section;
}

const SECTION_HEADING_KO: Record<string, string> = {
  summary: "핵심 요약",
  "topic overview": "주제 정리",
  background: "어디서 다루는지",
  "main content": "핵심 내용",
  "practical notes": "실무상 주의할 점",
  "open questions": "확인해야 할 질문",
  "source documents": "근거 문서",
  "key facts": "주요 내용",
  concepts: "관련 개념",
  "source notes": "소스 노트",
  "source anchors": "소스 앵커",
  verification: "검증",
  "detected contradictions": "탐지된 모순",
  sources: "소스",
  maintenance: "유지보수",
};

export function sectionHeadingKo(heading: string): string {
  return SECTION_HEADING_KO[normalizeSectionHeading(heading)] || heading;
}

export function isBoilerplateSummary(items: string[]): boolean {
  if (items.length === 0) return true;
  return items.every(
    (item) =>
      /^appears in \d+ source/i.test(item) ||
      /^\d+개 소스에서 (추출|정리)된 개념입니다/.test(item),
  );
}

export function normalizeInsight(text: string): string {
  return text.trim().replace(/\s+/g, " ").toLowerCase();
}

export function dedupeInsights(items: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of items) {
    const key = normalizeInsight(item);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(item.trim());
  }
  return out;
}

export type WikiSourceCard = {
  source: string;
  filename: string;
  description: string;
  showDescription: boolean;
};

export type WikiArticleModel = {
  introLine: string | null;
  documentMeta: WikiDocumentMeta | null;
  noteSections: WikiNoteSection[];
  sources: WikiSourceCard[];
  linkedSourcePages: string[];
  openQuestions: string[];
  practicalNotes: string[];
  hasBody: boolean;
  recommendedQuestions: string[];
};

export type WikiDocumentMeta = {
  documentTitle?: string;
  documentNumber?: string;
  writtenAt?: string;
  author?: string;
  caseCode?: string;
  vaultPath?: string;
  disclaimer?: string;
};

export type WikiNoteSection = {
  key: string;
  title: string;
  items: string[];
  prose: string;
};

const NOTE_SECTION_ORDER: Array<{ key: string; title: string }> = [
  { key: "background", title: "어디서 다루는지" },
  { key: "main content", title: "핵심 내용" },
  { key: "practical notes", title: "실무상 주의할 점" },
  { key: "open questions", title: "확인할 항목" },
];

function sectionProse(section: WikiSection | undefined): string {
  if (!section) return "";
  const lines = section.body
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !/^[-*]\s+/.test(line) && !/^\d+\.\s+/.test(line));
  return lines.join(" ").replace(/\s+/g, " ").trim();
}

function sectionItemsOrProse(section: WikiSection | undefined): { items: string[]; prose: string } {
  if (!section) return { items: [], prose: "" };
  const items = section.items;
  const prose = items.length > 0 ? "" : sectionProse(section);
  return { items, prose };
}


function mergeDocumentMeta(
  ...metas: Array<WikiDocumentMeta | null | undefined>
): WikiDocumentMeta | null {
  const merged: WikiDocumentMeta = {};
  for (const meta of metas) {
    if (!meta) continue;
    if (meta.documentTitle && !merged.documentTitle) merged.documentTitle = meta.documentTitle;
    if (meta.documentNumber && !merged.documentNumber) merged.documentNumber = meta.documentNumber;
    if (meta.writtenAt && !merged.writtenAt) merged.writtenAt = meta.writtenAt;
    if (meta.author && !merged.author) merged.author = meta.author;
    if (meta.caseCode && !merged.caseCode) merged.caseCode = meta.caseCode;
    if (meta.vaultPath && !merged.vaultPath) merged.vaultPath = meta.vaultPath;
    if (meta.disclaimer && !merged.disclaimer) merged.disclaimer = meta.disclaimer;
  }
  return Object.keys(merged).length > 0 ? merged : null;
}

const META_FIELD_PATTERNS: Array<{ field: keyof WikiDocumentMeta; pattern: RegExp }> = [
  { field: "documentTitle", pattern: /^문서명\s*[:：]\s*(.+)$/i },
  { field: "documentNumber", pattern: /^(?:문서번호|내부 문서번호)\s*[:：]\s*(.+)$/i },
  { field: "writtenAt", pattern: /^작성일\s*[:：]\s*(.+)$/i },
  { field: "author", pattern: /^담당\s*[:：]\s*(.+)$/i },
  { field: "caseCode", pattern: /^사건 코드\s*[:：]\s*(.+)$/i },
];

function isBoilerplateContentItem(text: string): boolean {
  const normalized = text.trim();
  if (!normalized) return true;
  return (
    /^(검색 키워드|문서 검토 표|source anchor|소스 앵커)/i.test(normalized) ||
    /RAG\s*(테스트|검색)|데모 vault|OH-MY-NEURO 데모|가상 테스트 데이터/i.test(normalized) ||
    /^\[page=\d+\]/i.test(normalized)
  );
}

function isDisclaimerItem(text: string): boolean {
  return /OH-MY-NEURO|데모용|가상 테스트|허구|실제 법률 자문/i.test(text);
}

export function extractDocumentMeta(
  items: string[],
  vaultPath?: string,
): { meta: WikiDocumentMeta | null; contentItems: string[] } {
  const meta: WikiDocumentMeta = {};
  const contentItems: string[] = [];

  for (const item of items) {
    let matched = false;
    for (const { field, pattern } of META_FIELD_PATTERNS) {
      const match = item.match(pattern);
      if (match) {
        meta[field] = match[1].trim();
        matched = true;
        break;
      }
    }
    if (matched) continue;

    if (isDisclaimerItem(item)) {
      meta.disclaimer = item;
      continue;
    }

    if (isBoilerplateContentItem(item)) continue;

    contentItems.push(item);
  }

  if (vaultPath) meta.vaultPath = vaultPath;

  const hasMeta = Boolean(
    meta.documentTitle ||
      meta.documentNumber ||
      meta.writtenAt ||
      meta.author ||
      meta.caseCode ||
      meta.disclaimer ||
      meta.vaultPath,
  );

  return { meta: hasMeta ? meta : null, contentItems };
}

function buildOverviewSection(
  summaryItems: string[],
  overviewSection: WikiSection | undefined,
): WikiNoteSection | null {
  const overviewProse = sectionProse(overviewSection);

  if (overviewProse) {
    return { key: "topic overview", title: "개요", items: [], prose: overviewProse };
  }

  if (summaryItems.length > 0) {
    if (summaryItems.length === 1) {
      return { key: "topic overview", title: "개요", items: [], prose: summaryItems[0] };
    }
    return { key: "topic overview", title: "개요", items: summaryItems, prose: "" };
  }

  return null;
}

export function buildWikiNoteSections(parsed: WikiParsedContent): { sections: WikiNoteSection[]; documentMeta: WikiDocumentMeta | null } {
  const overviewSection = findWikiSection(parsed, "topic overview");
  const summarySection = findWikiSection(parsed, "summary");
  const mainSection = findWikiSection(parsed, "main content");
  const sections: WikiNoteSection[] = [];

  const summaryExtract = extractDocumentMeta(summarySection?.items ?? []);
  const mainExtract = extractDocumentMeta(mainSection?.items ?? [], parsed.sourceMeta.source);
  const documentMeta = mergeDocumentMeta(summaryExtract.meta, mainExtract.meta);

  const overview = buildOverviewSection(summaryExtract.contentItems, overviewSection);
  if (overview) sections.push(overview);

  const summaryKeys = new Set(summaryExtract.contentItems.map(normalizeInsight));
  const mainItems = dedupeInsights(
    mainExtract.contentItems.filter((item) => !summaryKeys.has(normalizeInsight(item))),
  );

  if (mainItems.length > 0) {
    sections.push({ key: "main content", title: "핵심 내용", items: mainItems, prose: "" });
  }

  for (const { key, title } of NOTE_SECTION_ORDER) {
    if (key === "main content") continue;
    const section = findWikiSection(parsed, key);
    const { items, prose } = sectionItemsOrProse(section);
    if (items.length === 0 && !prose) continue;
    sections.push({ key, title, items, prose });
  }

  return { sections, documentMeta };
}

export function findWikiSection(parsed: WikiParsedContent, ...normalizedNames: string[]): WikiSection | undefined {
  return parsed.sections.find((section) => normalizedNames.includes(section.normalized));
}

export function hasSubstantialBody(parsed: WikiParsedContent): boolean {
  const ignored = new Set([
    "verification",
    "source anchors",
    "concepts",
    "sources",
    "maintenance",
    "detected contradictions",
  ]);
  return parsed.sections.some((section) => {
    if (ignored.has(section.normalized)) return false;
    return section.items.length > 0 || sectionProse(section).length > 0;
  });
}

export function extractLinkedVaultSources(parsed: WikiParsedContent): string[] {
  const sourceNotes = findWikiSection(parsed, "source notes");
  const sourceDocs = findWikiSection(parsed, "source documents");
  const paths = new Set<string>();
  for (const item of [...(sourceNotes?.items ?? []), ...(sourceDocs?.items ?? [])]) {
    const note = parseSourceNote(item);
    if (note.source) paths.add(note.source);
  }
  if (parsed.sourceMeta.source) paths.add(parsed.sourceMeta.source);
  return [...paths];
}

export function getRecommendedQuestions(pageTitle: string, openQuestions: string[]): string[] {
  const defaults = [
    `"${pageTitle}"와 관련된 핵심 리스크를 알려줘`,
    `"${pageTitle}" 관련 문서에서 확인해야 할 조항을 찾아줘`,
    `"${pageTitle}" 내용과 충돌하는 문서가 있는지 확인해줘`,
  ];
  const merged = [...openQuestions.filter(Boolean), ...defaults];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of merged) {
    const key = normalizeInsight(item);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(item);
    if (out.length >= 4) break;
  }
  return out.slice(0, 4);
}

export function buildWikiArticleModel(
  parsed: WikiParsedContent,
  pageTitle: string,
  linkedSourcePages: string[] = [],
): WikiArticleModel {
  const sourceNotesSection = findWikiSection(parsed, "source notes");
  const sourceDocsSection = findWikiSection(parsed, "source documents", "source notes");
  const questionsSection = findWikiSection(parsed, "open questions");
  const practicalSection = findWikiSection(parsed, "practical notes");
  const { sections: noteSections, documentMeta } = buildWikiNoteSections(parsed);

  const sourceItems = sourceDocsSection?.items ?? sourceNotesSection?.items ?? [];
  const sources: WikiSourceCard[] = sourceItems.map((item) => {
    const note = parseSourceNote(item);
    const source = note.source || item;
    const filename = source.split("/").pop() || source;
    const desc = note.description.trim();
    return {
      source,
      filename,
      description: desc,
      showDescription: Boolean(desc),
    };
  });

  if (sources.length === 0 && parsed.sourceMeta.source) {
    const source = parsed.sourceMeta.source;
    sources.push({
      source,
      filename: source.split("/").pop() || source,
      description: "",
      showDescription: false,
    });
  }

  const openQuestions = dedupeInsights(questionsSection?.items ?? []);
  const practicalNotes = dedupeInsights(practicalSection?.items ?? []);
  const introSection = noteSections.find((section) => section.key === "topic overview");
  const introLine = introSection?.prose || noteSections.find((section) => section.key === "main content")?.items[0] || null;

  return {
    introLine,
    documentMeta,
    noteSections,
    sources,
    linkedSourcePages,
    openQuestions,
    practicalNotes,
    hasBody: noteSections.length > 0 || hasSubstantialBody(parsed),
    recommendedQuestions: getRecommendedQuestions(pageTitle, openQuestions),
  };
}

export function cleanWikiExcerpt(excerpt?: string | null): string {
  if (!excerpt) return "";
  return excerpt
    .replace(/Generated at:\s*\S+/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

const WIKI_LINK_RE = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g;

export type WikiDisplayModel = {
  heroSubtitle: string | null;
  heroHint: string | null;
  insights: string[];
  showInsightsSection: boolean;
  sources: WikiSourceCard[];
  showSourcesSection: boolean;
};

export type TopicChatParams = {
  topicTitle: string;
  topicPage: string;
  topicSummary: string;
};

export function buildWikiDisplayModel(
  parsed: WikiParsedContent,
  summarySection: WikiSection | undefined,
  sourceNotesSection: WikiSection | undefined,
): WikiDisplayModel {
  const boilerplate = summarySection ? isBoilerplateSummary(summarySection.items) : true;
  const fallbackFromSources =
    boilerplate && sourceNotesSection
      ? sourceNotesSection.items.map((item) => parseSourceNote(item).description).filter(Boolean)
      : [];
  const rawSummary =
    boilerplate && fallbackFromSources.length > 0
      ? fallbackFromSources
      : summarySection?.items ?? [];

  const insights = dedupeInsights(rawSummary.filter(Boolean));
  const insightKeys = new Set(insights.map(normalizeInsight));

  const sourceSection = sourceNotesSection ?? findWikiSection(parsed, "source documents");
  const sources: WikiSourceCard[] = (sourceSection?.items ?? []).map((item) => {
    const note = parseSourceNote(item);
    const filename = note.source.split("/").pop() || note.source;
    const desc = note.description.trim();
    const showDescription = Boolean(desc) && !insightKeys.has(normalizeInsight(desc));
    return { source: note.source, filename, description: desc, showDescription };
  });

  let heroSubtitle: string | null = null;
  let heroHint: string | null = null;
  let showInsightsSection = false;

  if (insights.length === 0) {
    heroHint = parsed.excerpt || null;
  } else if (insights.length === 1) {
    heroSubtitle = insights[0];
    showInsightsSection = false;
  } else {
    heroHint = `${insights.length}개의 핵심 포인트`;
    showInsightsSection = true;
  }

  return {
    heroSubtitle,
    heroHint,
    insights,
    showInsightsSection,
    sources,
    showSourcesSection: sources.length > 0,
  };
}

export function getTopicSummary(parsed: WikiParsedContent, display: WikiDisplayModel): string {
  return display.heroSubtitle || display.insights[0] || parsed.excerpt || "Wiki에서 정리된 주제입니다.";
}

export function getPrimaryInsights(display: WikiDisplayModel, limit = 4): string[] {
  if (display.insights.length > 0) return display.insights.slice(0, limit);
  return display.sources
    .map((source) => source.description)
    .filter(Boolean)
    .slice(0, limit);
}

export function buildTopicChatParams(page: { title: string; path: string }, summary: string): TopicChatParams {
  return {
    topicTitle: page.title,
    topicPage: page.path,
    topicSummary: summary,
  };
}

export function topicParamsToSearch(params: TopicChatParams): string {
  const search = new URLSearchParams();
  search.set("topicTitle", params.topicTitle);
  search.set("topicPage", params.topicPage);
  search.set("topicSummary", params.topicSummary);
  return search.toString();
}

export function parseWikiLinks(text: string): WikiLink[] {
  const links: WikiLink[] = [];
  for (const match of text.matchAll(WIKI_LINK_RE)) {
    const pageId = match[1].trim();
    const label = (match[2] || pageId).trim();
    links.push({ pageId, label });
  }
  return links;
}

export function replaceWikiLinksWithMarkdown(text: string): string {
  return text.replace(WIKI_LINK_RE, (_full, path: string, label?: string) => {
    const pageId = path.trim();
    const display = (label || pageId).trim();
    return `[${display}](wiki://${encodeURIComponent(pageId)})`;
  });
}

function stripHtmlComments(content: string): { text: string; meta: Record<string, string> } {
  const meta: Record<string, string> = {};
  const text = content.replace(/<!--\s*([^:]+):\s*([^-]+?)\s*-->/g, (_m, key: string, value: string) => {
    meta[key.trim()] = value.trim();
    return "";
  });
  return { text: text.trim(), meta };
}

function extractTitle(lines: string[]): { title: string; rest: string[] } {
  if (lines[0]?.startsWith("# ")) {
    return { title: lines[0].slice(2).trim(), rest: lines.slice(1) };
  }
  return { title: "", rest: lines };
}

function extractGeneratedAt(lines: string[]): { generatedAt: string | null; rest: string[] } {
  const rest: string[] = [];
  let generatedAt: string | null = null;
  for (const line of lines) {
    const match = line.match(/^Generated at:\s*(.+)$/i);
    if (match) {
      generatedAt = match[1].trim();
      continue;
    }
    rest.push(line);
  }
  return { generatedAt, rest };
}

function parseItems(body: string): string[] {
  return body
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.replace(/^[-*]\s+/, "").replace(/^\d+\.\s+/, "").trim())
    .filter((line) => !["none", "없음"].includes(line.toLowerCase()));
}

function parseSections(lines: string[]): { sections: WikiSection[]; preamble: string } {
  const sections: WikiSection[] = [];
  const preambleLines: string[] = [];
  let current: WikiSection | null = null;
  let bodyLines: string[] = [];

  function flush() {
    if (!current) return;
    const body = bodyLines.join("\n").trim();
    sections.push({
      heading: current.heading,
      normalized: current.normalized,
      body,
      items: parseItems(body),
    });
    bodyLines = [];
  }

  for (const line of lines) {
    if (line.startsWith("## ")) {
      flush();
      const heading = line.slice(3).trim();
      current = { heading, normalized: normalizeSectionHeading(heading), body: "", items: [] };
      continue;
    }
    if (!current) {
      if (line.trim()) preambleLines.push(line);
      continue;
    }
    bodyLines.push(line);
  }
  flush();

  return { sections, preamble: preambleLines.join("\n").trim() };
}

export function parseWikiContent(raw: string): WikiParsedContent {
  const { text, meta } = stripHtmlComments(raw);
  const lines = text.split("\n");
  const { title, rest: afterTitle } = extractTitle(lines);
  const { generatedAt, rest: afterMeta } = extractGeneratedAt(afterTitle);
  const { sections, preamble } = parseSections(afterMeta);

  const excerptText = [...sections.flatMap((s) => s.items), preamble]
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();

  return {
    title,
    generatedAt: generatedAt || meta["updated-at"] || null,
    sourceMeta: meta,
    sections,
    preamble,
    excerpt: excerptText.slice(0, 160),
  };
}

export function isKnownSection(section: WikiSection): boolean {
  return KNOWN_SECTIONS.has(section.normalized);
}

export function parseSourceNote(item: string): { source: string; description: string } {
  const colon = item.indexOf(":");
  if (colon === -1) return { source: item, description: "" };
  return {
    source: item.slice(0, colon).trim(),
    description: item.slice(colon + 1).trim(),
  };
}

export function parseConceptItem(item: string): { name: string; description: string; pageId?: string } {
  const link = parseWikiLinks(item)[0];
  if (link) {
    return { name: link.label, description: "", pageId: link.pageId };
  }
  const colon = item.indexOf(":");
  if (colon === -1) return { name: item, description: "" };
  const name = item.slice(0, colon).trim();
  const rest = item.slice(colon + 1).trim();
  const countMatch = rest.match(/^\((\d+)\s+sources?\)$/i);
  if (countMatch) {
    return { name, description: rest };
  }
  return { name, description: rest };
}

export function relativeTimeFromIso(value?: string | null): string {
  if (!value) return "없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "방금";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}시간 전`;
  return `${Math.floor(seconds / 86400)}일 전`;
}
