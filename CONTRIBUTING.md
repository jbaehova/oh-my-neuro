# Contributing to OH-MY-NEURO

OH-MY-NEURO is a local-first RAG workspace for indexing and querying private knowledge. Contributions should preserve the project's core priorities: local data ownership, source-grounded answers, and careful handling of private user data.

## Before You Start

- Check existing issues and pull requests before opening a new one.
- For large feature changes, data model changes, or MCP integration changes, open an issue first to align on the approach.
- Do not commit `.env`, API keys, Vault documents, Chroma data, or generated build output.

## Reporting Issues

When reporting a bug, include as much of the following information as possible:

- Operating system, Python version, and Node.js version
- Command that was run or UI path that was used
- Expected behavior and actual behavior
- Steps to reproduce the issue
- Relevant logs or screenshots
- For configuration issues, include sanitized details based on `server/configs/app.yaml`, `server/configs/mcp_servers.yaml`, or relevant environment variables.

Do not include secrets, private document contents, tokens, or personal data in public issues.

## Development Setup

```bash
git clone <repo-url>
cd oh-my-neuro

uv sync --project server --extra dev
npm ci --prefix client
```

Set `OPENAI_API_KEY` in your shell before starting the server, or add it from the Settings screen after startup. If you use the bundled Korean law MCP server, configure `OPEN_LAW_ID` as well.

```bash
export OPENAI_API_KEY=your_openai_api_key
npm run build --prefix client
uv run --project server oh-my-neuro ui
```

For client development, run Vite separately:

```bash
npm run dev --prefix client
uv run --project server oh-my-neuro ui
```

## Pull Request Guidelines

- Keep each pull request focused on one purpose.
- Explain what changed, why it changed, and how it was validated.
- Include screenshots or a short visual description for UI changes.
- Update README or related documentation when changing configuration, storage format, API responses, or CLI behavior.
- When changing LLM prompts, retrieval routing, or MCP calls, validate answer quality and fallback behavior.

## Code Style

- Python code should follow the Python 3.11 target and the Ruff configuration in `server/pyproject.toml`.
- Prefer the existing FastAPI router patterns and Pydantic schemas at API boundaries.
- Client code should follow the existing Vite, React, TypeScript, Tailwind CSS, and `client/src/components` patterns.
- Treat user-provided Vault files, local configuration, and external MCP results as untrusted inputs.
- Keep unrelated refactors, formatting churn, and large file moves separate from functional changes.

## Validation

Before opening a pull request, run the commands that match your change:

```bash
# Server tests
uv run --project server pytest server/tests

# Python lint
uv run --project server ruff check server/app server/tests

# Client lint
npm run lint --prefix client

# Type-check and build client
npm run build --prefix client
```

There is no client test runner yet, so UI changes should be validated with ESLint, the Vite production build, and a manual browser check.

## Documentation

- Update README when user flows, configuration keys, CLI commands, or API responses change.
- Document required environment variables and network access when adding a new MCP server or external dependency.
- Review the README Security Notes when changing security-sensitive behavior or private data handling.

## Community Expectations

- Keep discussions focused on solving the problem and treat other contributors with respect.
- Good review comments include reproducible evidence, code locations, and practical alternatives.
- If a maintainer requests changes, respond clearly with what was updated or why a different approach was chosen.
