# Architecture

NeuNote is a local-first monorepo with a FastAPI backend and a React frontend. Runtime user data is stored outside the source checkout in an independent knowledge-base root (default `~/.neunote`).

## Runtime Shape

```text
Browser
  │
  │ HTTP / Server-Sent Events
  ▼
FastAPI backend
  │
  ├── YAML paper records
  ├── source PDFs
  ├── job logs
  ├── chat session JSON files
  └── optional agent/translation services
```

## Backend

Backend code lives in `backend/app/`.

- `main.py`: FastAPI routes, request models, streaming chat endpoints, background job entry points.
- `kb.py`: knowledge-base filesystem operations, paper CRUD, job persistence, session persistence, duplicate detection, enrichment helpers.
- `agent_chat.py`: Claude Code SDK integration, scoped paper chat, librarian tools, and paper review flows.
- `mineru.py`: MinerU CLI integration for remote PDF parsing, parsed Markdown/JSON retention, and extracted-image asset import.
- `librarian.py`: DBLP/OpenAlex/Crossref/arXiv aggregation, confirmation actions, metadata merge, safe PDF downloading, and SQLite FTS5 indexing.
- `figure_tools.py`: PyMuPDF/Pillow helpers for rendering PDF pages and extracting key-figure crops.
- `translate.py`: local Argos Translate and LLM-backed translation utilities.

The backend treats the selected knowledge-base root as the source of truth. `resolve_root()` initializes a folder with the expected layout before route handlers operate on it.

## Frontend

Frontend code lives in `frontend/src/`.

- `main.tsx`: application state, route-like page switching, API calls, and React components.
- `styles.css`: global design system and page/component styles.

The frontend is intentionally a single-page app without a router dependency. Page state is held in the top-level `App` component.

## Chat Flow

1. The user starts a chat from the nav, dashboard, or paper detail page.
2. The composer can attach zero or more mentioned paper IDs.
3. `/api/chat/stream` sends `question`, `session_id`, and `paper_ids`.
4. `agent_chat.py` builds a constrained prompt and exposes only NeuNote tools.
5. The backend streams session, text deltas, tool calls, tool results, and done/error events.
6. The frontend stores text and tools as ordered segments so tool calls appear inline with the model response.
7. The backend appends messages to one JSON file per session under `logs/chat_sessions/`.

Discovery and downloads are confirmation-gated. The agent may create an expiring action under `logs/librarian_actions/`; only the confirmation API can import metadata or enqueue PDF downloads. Download jobs validate public URLs and PDFs, save atomically, then build the full-text index. Metadata-only papers remain usable through title and abstract but are excluded from full-text search.

## Knowledge-Base Boundaries

Chat tools are constrained to:

- `AGENT.md`
- `papers/`
- `logs/`
- source PDFs under `originals/papers/` through dedicated PDF tools only

The chat agent cannot use arbitrary shell, web, or raw filesystem tools. Background enrichment is separate: it sends the selected source PDF to MinerU, then asks the review model to fill the YAML profile from MinerU's parsed output.

## Release Checks

```bash
bun run check
```

The check command runs frontend TypeScript/Vite build, backend bytecode compilation, and backend unit tests. GitHub Actions runs the same command on pull requests.
