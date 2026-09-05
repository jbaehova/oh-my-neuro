"""Prompt templates for building the generated wiki."""

from __future__ import annotations

WIKI_SOURCE_SYSTEM = (
    "You maintain an internal knowledge wiki for a Korean law office from private Vault documents. "
    "Write practical, source-grounded notes in Korean unless the source is mostly English. "
    "Do not invent facts. If something is unclear, say '문서상 명확히 확인되지 않음'. "
    "Avoid repetitive AI phrasing such as only saying '중요합니다', '필요합니다', or '일반적으로'. "
    "Use concrete wording from the source about duties, deadlines, risks, rights, costs, evidence, and permissions. "
    "Use the exact Markdown section headings requested by the user."
)

WIKI_SOURCE_USER = (
    "Source path: {source}\n"
    "Document type: {doc_type}\n\n"
    "Document text:\n{text}\n\n"
    "Create a Markdown note with exactly these sections:\n"
    "# {title}\n"
    "## 핵심 요약\n"
    "Write 2-3 bullet points summarizing what this document covers. Each bullet should be a complete sentence.\n"
    "## 관련 배경\n"
    "Explain when and why this topic appears in the document. Use only context visible in the source.\n"
    "## 주요 내용\n"
    "Write 4-7 bullet points with concrete facts, clauses, obligations, dates, amounts, parties, or procedures from the source.\n"
    "## 실무상 주의할 점\n"
    "Write 3-6 bullet points about risks, deadlines, responsibilities, privacy, evidence, cost, or compliance issues that matter in legal office work.\n"
    "## 확인해야 할 질문\n"
    "Write 3-5 follow-up questions a staff member should verify. Use '- 없음' only if truly none.\n"
    "## 근거 문서\n"
    "- {source}\n"
    "## Concepts\n"
    "Bullets in the form '- Concept: short description'. Prefer 3-10 durable concepts.\n"
    "## Source Anchors\n"
    "Bullets that identify the strongest source locations for later verification.\n\n"
    "Rules:\n"
    "- Target roughly 500-900 Korean characters of substantive content across the sections.\n"
    "- Do not pad with generic statements.\n"
    "- Do not include 'Generated at' or other build metadata.\n"
)

WIKI_CONTRADICTION_SYSTEM = (
    "You compare two short concept descriptions extracted from different private documents. "
    "Reply with exactly one word: 'yes' if they materially contradict each other, otherwise 'no'. "
    "Treat missing detail, emphasis differences, or compatible perspectives as 'no'."
)

WIKI_CONTRADICTION_USER = (
    "Concept: {concept}\n"
    "Source A ({source_a}): {description_a}\n"
    "Source B ({source_b}): {description_b}\n"
    "Do these descriptions contradict each other?"
)

WIKI_CONCEPT_SYSTEM = (
    "You write internal knowledge notes for a Korean law office wiki. "
    "Synthesize multiple source excerpts into one readable topic page in Korean. "
    "Do not invent facts beyond the provided excerpts. "
    "Write like a staff knowledge note, not like an AI report. "
    "Avoid repeating the same sentence in multiple sections. "
    "Use the exact Markdown section headings requested by the user."
)

WIKI_CONCEPT_USER = (
    "Concept: {concept}\n\n"
    "Source excerpts:\n{source_blocks}\n\n"
    "Create a Markdown topic page with exactly these sections:\n"
    "# {concept}\n"
    "## 주제 정리\n"
    "Write 2-4 complete sentences that explain what this topic is, when it matters, and what the staff should know first.\n"
    "## 관련 배경\n"
    "Write 3-5 bullet points about when this topic appears in the source documents.\n"
    "## 핵심 내용\n"
    "Write 5-8 bullet points with concrete facts, duties, procedures, risks, dates, parties, or clauses from the excerpts. "
    "Add the source filename in parentheses at the end of each bullet when possible.\n"
    "## 실무상 주의할 점\n"
    "Write 3-5 bullet points about practical risks or mistakes to avoid.\n"
    "## 확인해야 할 질문\n"
    "Write 3-4 verification questions.\n"
    "## 근거 문서\n"
    "Bullets listing each source path provided above.\n\n"
    "Rules:\n"
    "- Target roughly 500-900 Korean characters of substantive content.\n"
    "- Do not use a one-line summary only.\n"
    "- Do not include 'Generated at' or other build metadata.\n"
)
