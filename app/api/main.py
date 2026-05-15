"""FastAPI entry point and SPA hosting."""

from __future__ import annotations

from pathlib import Path

from app.common.logging import get_logger
from app.config import AppConfig, get_config

log = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def create_app(cfg: AppConfig | None = None):
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    from app.api.routes import chat, health, settings, vault

    cfg = cfg or get_config()
    app = FastAPI(title=cfg.ui.title, version="0.4.0")
    app.state.config = cfg
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(vault.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")

    assets_dir = FRONTEND_DIST / "assets"
    index_html = FRONTEND_DIST / "index.html"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if index_html.exists():
            return FileResponse(index_html)
        return {
            "message": "프론트엔드 빌드가 없습니다. 개발 중에는 `npm run dev --prefix frontend`를 실행하세요.",
            "requested_path": path,
        }

    return app


def run_server(cfg: AppConfig | None = None, host: str | None = None, port: int | None = None) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI 서버 실행에는 uvicorn이 필요합니다.") from exc

    cfg = cfg or get_config()
    host = host or cfg.ui.host
    port = port or cfg.ui.port
    log.info("FastAPI UI 시작: http://%s:%d", host, port)
    uvicorn.run(create_app(cfg), host=host, port=port, log_level=cfg.app.log_level.lower())


app = create_app()
