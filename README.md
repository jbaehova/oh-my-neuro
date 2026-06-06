# OH-MY-NEURO

Local-first RAG workspace for your private document vault

내 문서, 위키, 법률/웹 근거를 하나의 답변으로 연결합니다.

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=111111)
![LangGraph](https://img.shields.io/badge/LangGraph-1.x-1C3C3C)
![OpenAI](https://img.shields.io/badge/OpenAI-API-412991?logo=openai&logoColor=white)
![Chroma](https://img.shields.io/badge/Chroma-local%20vector%20store-FC5A50)
![uv](https://img.shields.io/badge/uv-package%20manager-654FF0)
![Ruff](https://img.shields.io/badge/Ruff-lint-261230)

[Features](#features) • [Architecture](#architecture) • [Tech Stack](#tech-stack) • [Quick Start](#quick-start) • [Usage](#usage) • [Configuration](#configuration) • [Project Structure](#project-structure) • [Development](#development)

> OH-MY-NEURO는 Vault 디렉토리의 PDF, DOCX, Markdown, 텍스트 파일을 로컬 Chroma 인덱스로 동기화하고, LangGraph 기반 Corrective RAG로 질문을 재작성·검색·검증·답변합니다. 필요하면 생성된 Vault Wiki와 MCP 법률/웹검색 서버까지 함께 조회해 출처가 있는 답변을 만듭니다.

## Features

| Feature | Description |
| --- | --- |
| Vault Delta Sync | 파일 추가·수정·삭제를 감지해 변경분만 인덱싱합니다. |
| Corrective RAG | 질문 재작성, 검색, 관련도 필터링, 재시도, 컨텍스트 구성, 답변 생성을 LangGraph로 오케스트레이션합니다. |
| Generated Vault Wiki | Vault 문서를 요약한 `_omn_wiki` 페이지, Easy Index, 지식 그래프, Wiki 전용 벡터 인덱스를 제공합니다. |
| MCP Routing | 법률 질문은 `korean_law`, 최신/오늘/웹 질문은 `web_search` MCP 서버로 라우팅합니다. |
| Streaming Chat | FastAPI NDJSON 스트리밍과 React UI에서 토큰 단위 답변, 출처, 웹검색 상태를 표시합니다. |
| PDF-Aware Ingestion | PyMuPDF 기반 파서를 우선 사용하고 실패 시 `pypdf`로 폴백합니다. Tesseract OCR은 선택 기능입니다. |
| Local Vector Store | 원문 문서와 Wiki 인덱스를 ChromaDB 컬렉션으로 로컬 저장합니다. |
| CLI + UI | `oh-my-neuro` 명령어와 FastAPI/React UI를 모두 지원합니다. |

## Architecture

```text
Vault Directory
  ├─ PDF / DOCX / TXT / MD
  │
  ▼
scan_vault ──► delta planner ──► loaders ──► chunk_pages ──► embeddings ──► Chroma
                   │                 │                              │
                   │                 ├─ PyMuPDF / pypdf              ├─ raw document index
                   │                 ├─ python-docx                  └─ wiki document index
                   │                 └─ markdown / text
                   │
                   └─ deleted sources ──► index cleanup

Question
  │
  ▼
prepare_query ──► retrieve(raw + wiki) ──► grade ──► rewrite?
                                                      │
                                                      ▼
                                                route by intent
                                                ├─ local context
                                                ├─ MCP law search
                                                └─ MCP web search
                                                      │
                                                      ▼
                                             prepare_context ──► OpenAI LLM ──► Answer + citations
```

모든 검색 결과는 `Citation`으로 렌더링되며, Wiki 근거, 원문 문서 근거, MCP 법률/웹검색 근거가 하나의 컨텍스트 블록으로 합쳐집니다.

## Tech Stack

| Layer | Technology | Purpose |
| --- | --- | --- |
| API | FastAPI + Uvicorn | REST/streaming API, SPA hosting |
| UI | React 19 + Vite + TypeScript | Chat, Vault, Wiki, Settings 화면 |
| Orchestration | LangGraph | Corrective RAG 상태 그래프 |
| LLM | OpenAI via `langchain-openai` | 답변 생성, 질문 재작성, 선택적 관련도 판정 |
| Embeddings | `text-embedding-3-large` | 문서/Wiki 벡터화 |
| Vector Store | ChromaDB | 로컬 검색 인덱스 |
| Ingestion | PyMuPDF, pypdf, python-docx | PDF/DOCX/TXT/Markdown 로딩 |
| External Tools | MCP + `langchain-mcp-adapters` | 법률 검색, 웹검색, 사용자 추가 MCP 서버 |
| Config | Pydantic + YAML + `.env` | 앱, LLM, 검색, Wiki, MCP 설정 |
| Tooling | uv, pytest, Ruff, ESLint | 설치, 테스트, 린트, 프론트엔드 빌드 |

## Supported Inputs

| Category | Extensions / Source | Loader | Notes |
| --- | --- | --- | --- |
| PDF | `.pdf` | PyMuPDF, pypdf fallback | OCR은 Tesseract 설치 시 선택적으로 사용 |
| Word | `.docx` | python-docx | 문단 단위 텍스트 추출 |
| Text | `.txt` | built-in text loader | 일반 텍스트 문서 |
| Markdown | `.md`, `.markdown` | markdown/text loader | Vault Wiki와 일반 노트 모두 지원 |
| Wiki | `_omn_wiki/*.md` | Wiki vector store | Sync 후 자동 생성·인덱싱 가능 |
| External | MCP law/web tools | MCP client | 질문 의도에 따라 조건부 호출 |

## Quick Start

### Prerequisites

- Python 3.11
- `uv`
- Node.js compatible with Vite 6
- OpenAI API key
- Optional: Tesseract + Korean/English language data for scanned PDF OCR
- Optional: `OPEN_LAW_ID` for the bundled Korean law MCP server

### Installation

```bash
git clone <repo-url>
cd omn

uv venv --python 3.11
source .venv/bin/activate
uv pip install -e .[dev]

npm ci --prefix frontend
cp .env.example .env
```

Edit `.env` and set your API key:

```bash
OPENAI_API_KEY=your_openai_api_key_here
```

### Build and Run

```bash
npm run build --prefix frontend
oh-my-neuro ui
```

Open the local UI:

```text
http://127.0.0.1:7860
```

For frontend development, run Vite separately:

```bash
npm run dev --prefix frontend
oh-my-neuro ui
```

## Usage

### CLI Examples

```bash
# Set the Vault directory
oh-my-neuro vault ~/Documents/my-vault

# Preview sync changes without writing to Chroma
oh-my-neuro sync --dry-run

# Index changed files and rebuild Wiki when enabled
oh-my-neuro sync

# Ask against local Vault/Wiki context
oh-my-neuro ask "최근 회의록에서 결정된 액션 아이템을 정리해줘"

# Stream the answer in the terminal
oh-my-neuro ask "계약서의 해지 조항을 요약해줘" --stream

# Inspect local state
oh-my-neuro status
oh-my-neuro list

# Rebuild and validate the generated Wiki
oh-my-neuro wiki rebuild
oh-my-neuro wiki lint

# Clear all indexed chunks
oh-my-neuro clear --force
```

### CLI Reference

```text
Usage: oh-my-neuro [--config APP_YAML] <COMMAND>

Commands:
  ui                 FastAPI/React UI 실행 (기본)
  vault <path>       Vault 경로 설정
  sync [--dry-run]   Vault 델타 동기화
  status             Vault, sync, index 상태 요약
  ask <question>     RAG 질문 응답 (--stream 지원)
  list               인덱싱된 파일 목록
  clear --force      Chroma 인덱스 초기화
  wiki               Wiki 상태 출력
  wiki status        Wiki 상태 출력
  wiki rebuild       Wiki 재생성 및 인덱싱
  wiki lint          Wiki 페이지 점검
```

### HTTP API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/chat` | 단일 RAG 답변 생성 |
| `POST /api/chat/stream` | NDJSON 스트리밍 답변 |
| `GET /api/vault/status` | Vault, 인덱스, Wiki 상태 조회 |
| `POST /api/vault/sync` | 진행률 스트리밍 기반 Vault 동기화 |
| `GET /api/vault/files` | 인덱싱된 파일 목록 |
| `GET /api/wiki/pages` | 생성된 Wiki 페이지 목록 |
| `GET /api/wiki/easy-index` | 문서/Wiki 통합 검색 |
| `GET /api/wiki/graph` | Wiki 개념 그래프 |
| `GET /api/settings` | 현재 설정 조회 |
| `GET /api/settings/mcp/servers` | MCP 서버 목록 조회 |

## Configuration

Configuration is layered in this order:

| Source | Purpose |
| --- | --- |
| `configs/app.yaml` | 기본 앱, LLM, 검색, 저장소, Wiki, MCP, UI 설정 |
| `.env` | `OPENAI_API_KEY` 같은 로컬 비밀값 |
| `configs/mcp_servers.yaml` | 기본 번들 MCP 서버 |
| `~/.oh-my-neuro/mcp_servers.yaml` | UI에서 추가·수정·삭제한 사용자 MCP 서버 |

Default model and retrieval settings:

```yaml
llm:
  chat_model: gpt-5.4-mini
  grader_model: gpt-5.4-nano
  rewriter_model: gpt-5.4-nano
  embedding_model: text-embedding-3-large

retrieval:
  top_k: 5
  fetch_k: 12
  chunk_size: 1000
  chunk_overlap: 150
  max_rewrites: 1
```

Bundled MCP servers:

```yaml
servers:
  korean_law:
    transport: stdio
    command: uvx
    args: [korean-law-mcp]
    env:
      OPEN_LAW_ID: $OPEN_LAW_ID
    enabled: true
  web_search:
    transport: stdio
    command: uvx
    args: [duckduckgo-mcp-server]
    env:
      DDG_REGION: kr-kr
      DDG_SAFE_SEARCH: moderate
    enabled: true
```

MCP 서버는 Settings 화면에서 `stdio`, HTTP, SSE 계열 transport로 추가할 수 있습니다. Settings 화면 진입만으로는 외부 서버를 실행하지 않고, 연결 테스트나 실제 검색이 필요할 때 연결합니다.

## Project Structure

```text
omn/
├── app/
│   ├── api/                    # FastAPI app, routes, DTO schemas
│   │   └── routes/             # chat, vault, wiki, settings, health
│   ├── common/                 # shared models and logging
│   ├── config/                 # YAML/.env loader and Pydantic config
│   ├── ingestion/              # loaders, chunking, sync pipeline
│   ├── mcp/                    # MCP client and tool bridge
│   ├── rag/                    # LangGraph graph, prompts, OpenAI service
│   ├── storage/                # Chroma vector store adapter
│   ├── vault/                  # Vault scanner, delta manager, state
│   ├── wiki/                   # generated Wiki service, store, models
│   └── main.py                 # CLI entry point
│
├── frontend/
│   └── src/
│       ├── components/         # shared UI and Wiki visualizations
│       ├── hooks/              # React hooks
│       ├── lib/                # API client and utilities
│       └── pages/              # Chat, Vault, Wiki, Settings, onboarding
│
├── configs/
│   ├── app.yaml                # application defaults
│   └── mcp_servers.yaml        # bundled MCP server presets
├── tests/                      # pytest test suite
├── docs/                       # local PDF specs
├── pyproject.toml              # Python package, scripts, pytest, Ruff
├── frontend/package.json       # Vite/React scripts and dependencies
└── .env.example                # local environment template
```

## Development

```bash
# Backend tests
pytest

# Python lint
ruff check .

# Frontend lint
npm run lint --prefix frontend

# Type-check and build frontend
npm run build --prefix frontend
```

There is no frontend test runner yet, so UI changes should be validated with ESLint and the Vite production build.

### Design Principles

| Principle | Implementation |
| --- | --- |
| Local-first | Vault files, Chroma data, generated Wiki, and user MCP config stay on the local machine. |
| Source-grounded | Answers are generated from rendered context and returned with citations. |
| Progressive external search | MCP law/web tools run only when routing rules determine they are useful. |
| Graceful fallback | PDF parsing, LLM grading, query rewriting, Wiki retrieval, and MCP calls all have fallback paths. |
| Config-driven | YAML, `.env`, and Settings UI control runtime behavior without code changes. |
| Korean-first workflow | CLI/UI copy, legal routing keywords, and OCR defaults are tuned for Korean and English documents. |

## Security Notes

- Never commit `.env`, API keys, Vault documents, Chroma data, or generated build output.
- The Settings API stores `OPENAI_API_KEY` in the project `.env` and returns only a boolean configured state.
- External MCP servers may access network resources. Review `configs/mcp_servers.yaml` and user-added server specs before enabling them.
- Vault file opening is path-checked against the configured Vault root.

## License

No license file is currently included in this repository.
