# Changelog

All notable changes to NeuNote will be documented in this file.

The format is inspired by Keep a Changelog, and this project uses semantic versioning for formal releases.

## [1.0.0] - 2026-07-18

### Added

- Local-first paper library with YAML paper records and PDF ingestion.
- Dashboard, library, paper profile, jobs, settings, and chat views.
- Background enrichment jobs with queue status and concurrency settings.
- One-click stop-all action for active enrichment jobs.
- Independent chat module with session history stored in `logs/chat_sessions/`.
- Multi-paper mentions in chat and per-message mention display.
- Agent tools for paper YAML reads, precise PDF page text extraction, visual PDF page rendering, and verified paper updates.
- Streaming markdown chat UI with interleaved tool-call status blocks.
- Structured enrichment for author teams, core concepts, summaries, methods, experiments, limitations, and key figures.
- Configurable key-figure extraction with fast Pillow detection and agent-guided PyMuPDF tools.
- Bilingual detail-page rendering for summaries, core concepts, and key-figure descriptions.
- Review-note search across the library.
- Optional local and LLM-backed translation workflows.
- Optional Git sync for a separate knowledge-base repository.
- GitHub issue templates, pull request template, and CI check workflow.

### Notes

- This is the first formal open-source release line.
