"""Prompt templates for building the generated wiki."""

from __future__ import annotations

WIKI_SOURCE_SYSTEM = (
    "You maintain a local Markdown wiki from a user's private Vault documents. "
    "Create conservative, source-grounded notes. Do not invent facts. "
    "Write in Korean unless source text is mostly English. "
    "Use the exact Markdown section headings requested by the user."
)

WIKI_SOURCE_USER = (
    "Source path: {source}\n"
    "Document type: {doc_type}\n\n"
    "Document text:\n{text}\n\n"
    "Create a Markdown note with exactly these sections:\n"
    "# {title}\n"
    "## Summary\n"
    "A concise 3-6 bullet summary.\n"
    "## Key Facts\n"
    "Bullets with concrete facts. Include page/location hints when visible in the text.\n"
    "## Concepts\n"
    "Bullets in the form '- Concept: short description'. Prefer 3-10 durable concepts.\n"
    "## Open Questions\n"
    "Bullets for missing, ambiguous, or unresolved points. Use '- None' if there are none.\n"
    "## Source Anchors\n"
    "Bullets that identify the strongest source locations for later verification.\n"
)
