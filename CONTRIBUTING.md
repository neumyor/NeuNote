# Contributing

Thanks for taking the time to improve NeuNote.

## Development Setup

```bash
bun install
cd frontend && bun install && cd ..
cd backend && uv sync && cd ..
bun run dev
```

## Checks

Run these before opening a pull request:

```bash
bun run check
```

This runs the frontend build and Python bytecode compilation for the backend application modules.

## Pull Request Guidelines

- Keep changes scoped and explain the user-facing behavior they affect.
- Do not commit source PDFs, private notes, API keys, local logs, or machine-specific configuration.
- Include screenshots or short screen recordings for substantial UI changes.
- Preserve local-first behavior. Features should work against an ordinary folder on disk.
- Prefer structured parsing and typed APIs over ad hoc text manipulation.

## Code Style

- Frontend: React + TypeScript, functional components, existing CSS design tokens.
- Backend: Python 3.11+, FastAPI, Pydantic models, small focused functions.
- Comments should explain non-obvious behavior rather than restating code.

## Data Fixtures

The repository includes sample paper YAML records in `papers/`. Treat those as demo data, not as tests. Avoid adding large fixtures or copyrighted PDFs.
