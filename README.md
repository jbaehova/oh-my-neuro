## 실행 방법

Python 환경은 `venv` 또는 `uv` 중 하나만 사용하면 됩니다.

### 1. 저장소 클론

```bash
git clone <repo-url>
cd omn
```

### 2. Python 의존성 설치

`venv`를 쓰는 경우:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

`uv`를 쓰는 경우:

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e .[dev]
```

PDF 인덱싱은 기본적으로 PyMuPDF 기반 파서를 먼저 사용하고, 실패하면 기존 `pypdf`로 폴백합니다.
스캔 PDF OCR까지 사용하려면 Tesseract와 한국어/영어 언어 데이터를 별도로 설치해야 합니다.

### 3. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어서 OpenAI API 키를 넣습니다.

```bash
OPENAI_API_KEY=your_api_key_here
```

### 4. 프론트엔드 빌드

```bash
npm ci --prefix frontend
npm run build --prefix frontend
```

### 5. UI 실행

```bash
oh-my-neuro ui
```

브라우저에서 아래 주소로 접속합니다.

```text
http://127.0.0.1:7860
```

## MCP 외부 서버 설정

MCP는 기본적으로 켜져 있으며, 설치 직후 법률 검색 서버와 웹검색 서버가 함께 등록됩니다.
기본 번들 설정은 `configs/mcp_servers.yaml`에 있고, 사용자가 UI에서 추가/수정/삭제한 서버는
`~/.oh-my-neuro/mcp_servers.yaml`에 저장됩니다. Settings 화면 진입만으로는 MCP 서버를 실행하지 않고,
`연결 테스트`를 누르거나 Chat에서 실제 검색이 필요할 때 연결합니다.

```yaml
servers:
  korean_law:
    transport: stdio
    command: uvx
    args:
      - korean-law-mcp
    env:
      OPEN_LAW_ID: $OPEN_LAW_ID
    enabled: true
  web_search:
    transport: stdio
    command: uvx
    args:
      - duckduckgo-mcp-server
    env:
      DDG_REGION: kr-kr
      DDG_SAFE_SEARCH: moderate
    enabled: true
```

웹검색은 Chat 입력창에서 기본 ON입니다. 다만 로컬 Vault/Wiki 근거가 충분한 일반 문서 질문은 외부 웹검색을
호출하지 않고, 최신/오늘/뉴스 같은 질문이나 내부 근거가 부족한 질문에서 웹검색 MCP를 사용합니다.
HTTP/SSE 기반 외부 MCP 서버는 Settings 화면에서 `transport`, `url`, `headers`를 입력해 추가할 수 있습니다.
