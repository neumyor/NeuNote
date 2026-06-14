# NeuNote

NeuNote is a local-first literature workspace for managing PDFs, structured paper notes, background enrichment jobs, and agent-assisted paper chat.

It is built as a small monorepo:

- `backend/`: FastAPI service for the knowledge base, PDF ingestion, enrichment jobs, translation, and agent chat.
- `frontend/`: Vite + React + TypeScript application.
- `papers/`, `originals/`, `logs/`, `metadata/`: the default local knowledge-base root used during development.

NeuNote keeps your library on disk. Paper records are YAML files, source PDFs stay under `originals/papers/`, and chat sessions are stored as one JSON file per conversation under `logs/chat_sessions/`.

## Highlights

- PDF upload and local library management.
- Structured YAML paper records with tags, status, summaries, methods, experiments, limitations, and review notes.
- Dashboard, library, profile, jobs, settings, and independent chat views.
- Independent chat module with persisted session history.
- Multi-paper mentions in chat, including `@` paper search and per-message mention context.
- Agent tools for reading paper YAML files, reading exact PDF pages, rendering PDF pages as images, and writing verified paper updates.
- Streaming ChatGPT-style UI with interleaved tool calls and markdown rendering.
- Background enrichment queue with per-paper job status.
- Optional local translation via Argos Translate or LLM-backed translation.

## Requirements

- macOS, Linux, or WSL.
- Python 3.11 or newer.
- [uv](https://docs.astral.sh/uv/) for Python dependency management.
- [Bun](https://bun.sh/) for frontend tooling and the root dev runner.
- `pdftoppm` for visual PDF page rendering in agent chat.
  - macOS: `brew install poppler`
  - Debian/Ubuntu: `sudo apt-get install poppler-utils`
- Optional: an Anthropic-compatible API key and Claude Code SDK/CLI setup for agent workflows.

## Quick Start

```bash
git clone <your-fork-or-repo-url>
cd Readinglist
bun install
cd frontend && bun install && cd ..
cd backend && uv sync && cd ..
bun run dev
```

Then open:

- Frontend: http://127.0.0.1:5173
- Backend: http://127.0.0.1:8765

The root dev command starts both services and sets `KB_DEFAULT_ROOT` to the repository root. You can change the knowledge-base root from the Settings page.

## Common Commands

```bash
# Start frontend and backend together
bun run dev

# Build the frontend
bun run build

# Run basic project checks
bun run check

# Backend only
cd backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8765

# Frontend only
cd frontend
bun run dev -- --host 127.0.0.1 --port 5173
```

## Knowledge-Base Layout

A NeuNote knowledge base is a regular folder:

```text
.
├── AGENT.md
├── metadata/
│   └── app_config.yaml
├── originals/
│   └── papers/
├── papers/
│   └── <paper_id>.yaml
└── logs/
    ├── chat_sessions/
    ├── jobs/
    └── debug/
```

Runtime configuration and logs can contain local paths, API keys, and private research notes. They are ignored by default where appropriate. Source PDFs are also ignored because they are usually large and may be copyrighted.

See [docs/knowledge-base.md](docs/knowledge-base.md) for the paper YAML shape and persistence details.

## Agent Chat

Chat is an independent module rather than a paper-detail subview. It supports:

- starting from the dashboard with no selected paper,
- opening from a paper detail page with that paper automatically mentioned,
- mentioning multiple papers from the composer with `@`,
- persisted chat history,
- streaming markdown responses,
- folded tool parameters and results,
- user-facing tool intent labels,
- exact-page PDF text reads and visual page rendering.

The agent is constrained to NeuNote tools and cannot directly use arbitrary filesystem or shell tools from the chat surface.

## Configuration

Settings are stored under the selected knowledge-base root in `metadata/app_config.yaml`.

Supported fields include:

```yaml
claude_api_key: ""
claude_endpoint: ""
claude_model: sonnet
max_concurrency: 4
translation_engine: local
```

`translation_engine` can be `local` or `llm`.

## Privacy and Data Notes

NeuNote is designed for local use. Before publishing your own library:

- do not commit `originals/papers/`,
- review `papers/*.yaml` for private notes,
- do not commit `metadata/app_config.yaml`,
- do not commit `logs/`.

The repository currently includes sample paper YAML records so the UI has meaningful data during development.

## Project Status

This is the first formal open-source release candidate. The codebase is usable locally and intentionally simple, but the API surface may still evolve.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
