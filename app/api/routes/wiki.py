"""Generated wiki routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import effective_config
from app.wiki.models import WikiBuildResult, WikiGraph, WikiLintIssue, WikiPageContent, WikiPageSummary, WikiStatus
from app.wiki.service import WikiService

router = APIRouter(prefix="/wiki", tags=["wiki"])


@router.get("/status", response_model=WikiStatus)
def status() -> WikiStatus:
    return WikiService(effective_config()).status()


@router.get("/pages", response_model=list[WikiPageSummary])
def pages(q: str = "") -> list[WikiPageSummary]:
    return WikiService(effective_config()).list_pages(q)


@router.get("/page", response_model=WikiPageContent)
def page(id: str) -> WikiPageContent:
    found = WikiService(effective_config()).get_page(id)
    if found is None:
        raise HTTPException(status_code=404, detail="Wiki page not found.")
    return found


@router.post("/rebuild", response_model=WikiBuildResult)
def rebuild(force: bool = True) -> WikiBuildResult:
    result = WikiService(effective_config()).rebuild(force=force)
    if result.error:
        raise HTTPException(status_code=400, detail=result.error)
    return result


@router.get("/lint", response_model=list[WikiLintIssue])
def lint() -> list[WikiLintIssue]:
    return WikiService(effective_config()).lint()


@router.get("/graph", response_model=WikiGraph)
def graph() -> WikiGraph:
    return WikiService(effective_config()).build_graph()
