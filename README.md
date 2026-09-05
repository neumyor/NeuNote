# NeuNote

NeuNote is a local-first literature management workspace for PDFs, structured paper enrichment, review notes, key-figure extraction, bilingual summaries, and agent-assisted paper chat.

The project is intentionally small:

- `backend/`: FastAPI service for the knowledge base, PDF ingestion, enrichment jobs, translation, Git sync, and chat.
- `frontend/`: Vite + React + TypeScript application.
- User data lives in a separate knowledge-base folder, defaulting to `~/.neunote`.

## Features

- Local PDF ingestion and YAML-backed paper records.
- Structured enrichment: bibliography metadata, author teams, core concepts, one-sentence summary, problem, contributions, method, experiments, limitations, and key figures.
- MinerU-backed PDF parsing before enrichment, with structured Markdown, layout-aware text, and extracted image assets.
- Bilingual detail pages with LLM-backed translation support and English reference text for technical terms.
- Review notes and a dedicated review-note search page.
- Background enrichment queue with per-paper status and one-click cancel-all.
- A paper librarian that preserves scoped paper chat while discovering conference papers, importing metadata with confirmation, downloading requested PDFs, and searching indexed full text.
- Optional Git sync for user data, with API keys and machine-local logs excluded.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for Python dependencies
- [Bun](https://bun.sh/) for frontend tooling
- Poppler for PDF page rendering
  - macOS: `brew install poppler`
  - Debian/Ubuntu: `sudo apt-get install poppler-utils`
- Optional: an Anthropic-compatible API key for enrichment, chat, and higher-quality translation
- MinerU CLI: `npm install -g mineru-open-api` (already installed by the bundled MinerU skill); a MinerU token enables precision parsing for large or complex papers.

## Quick Start

```bash
git clone <repo-url> neunote
cd neunote
bun install
cd frontend && bun install && cd ..
cd backend && uv sync && cd ..
bun run dev
```

Open http://127.0.0.1:5173.

The dev runner starts:

- Backend: http://127.0.0.1:8765
- Frontend: http://127.0.0.1:5173

By default, user data is stored in `~/.neunote`. Keep the knowledge-base folder outside the source checkout so your personal library and this code repository remain separate.

## Documentation

- [Installation and setup](docs/installation.md)
- [User guide](docs/user-guide.md)
- [Knowledge-base format](docs/knowledge-base.md)
- [Architecture](docs/architecture.md)
- [Contributing](CONTRIBUTING.md)

## Common Commands

```bash
# Start frontend and backend together
bun run dev

# Build frontend and run backend checks/tests
bun run check

# Backend only
cd backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8765

# Frontend only
cd frontend
bun run dev -- --host 127.0.0.1 --port 5173
```

## Privacy Model

NeuNote is local-first. Your papers, notes, chat history, and enrichment outputs are ordinary files in your knowledge-base folder.

Network discovery aggregates DBLP conference catalogues with OpenAlex, Crossref, and arXiv metadata. Search and venue lists are previews only. Metadata import and every PDF download require explicit UI confirmation. If one provider is unavailable, NeuNote returns results from the remaining providers and exposes a warning instead of silently reporting an empty result.

The source repository ignores runtime user data:

- `papers/`
- `originals/`
- `assets/paper_figures/`
- `logs/`
- `metadata/`
- local config files such as `.kb_app_config.yaml`

When Git sync is enabled, NeuNote initializes or uses a separate Git repository inside the selected knowledge-base folder. Paper YAML and extracted figure images are synced by default; chat sessions and source PDFs are opt-in; API keys, machine-local config, job logs, and debug logs are never synced.

## Release Status

This repository is prepared as the V1.1 release line. The app is designed for local deployment and personal or lab-scale literature workflows.

## License

MIT. See [LICENSE](LICENSE).
