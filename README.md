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
