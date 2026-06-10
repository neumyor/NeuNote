# NeuNote（纽记）

Local literature-library manager with a Python FastAPI backend and a Bun + TypeScript frontend.

## Start

```bash
bun run dev
```

- Frontend: http://127.0.0.1:5173
- Backend: http://127.0.0.1:8765

## Features

- Set the knowledge-base root directory from the UI.
- Empty roots are initialized with the expected folder structure.
- Upload PDFs into `originals/papers/`.
- Maintain canonical paper records in `metadata/papers.yaml`.
- Generate structured paper profiles in `metadata/profiles/`.
- Track identity, file paths, tags, reading status, review status, extraction warnings, and structured summary fields per paper.
- Generate first-pass Markdown paper cards in `memory/papers/` for human-readable notes.
- Queue per-paper background profile enrichment jobs after upload.
- Audit the library for missing, suspicious, stale, and file-related profile fields.
- Run deterministic profile refreshes before using agent-based validation.
- Run per-paper Agent Review to fill missing fields and validate existing fields against PDF text.
- Queue Agent Review jobs for all papers with validation issues.
- Monitor AI jobs with progress, runtime, pause/resume, cancel, and delete controls.
- Delete papers from the library, including profile, paper card, and source PDF.
- Browse the library through Dashboard, Library, Profile, Jobs, and Settings views.

## Profile Validation

Profile maintenance is intentionally split into two stages:

1. Deterministic refresh: local PDF metadata and extracted text are parsed into structured profile fields.
2. Agent Review: the agent receives the current profile plus PDF text, then writes a schema-compatible patch only for fields it can validate.

Agent Review is per-paper and is not run automatically across the whole library.

Agent Review is optimized to reduce token use:

- The agent reads the current structured profile first.
- It extracts only the first two PDF pages for title, authors, year, venue, DOI, arXiv, abstract, and problem validation.
- It requests more pages only when method, experiment, or limitation fields need deeper evidence.

## Agent Configuration

The Settings page accepts optional agent settings used by background extraction workflows:

- Anthropic API key
- Claude endpoint, optional
- Claude model

These values are persisted under the selected knowledge-base root:

```yaml
claude_api_key: ...
claude_endpoint: ...
claude_model: sonnet
```

The backend maps these settings to the Claude Code SDK environment:

```bash
ANTHROPIC_API_KEY=...
ANTHROPIC_BASE_URL=...
```

The `claude` CLI must be available to the backend process.

## Persistence

- Model settings: `metadata/app_config.yaml`
- Background memory jobs: `logs/memory_jobs/*.json`
- Structured paper profiles: `metadata/profiles/*.yaml`

Model settings and job logs may contain private local information.
