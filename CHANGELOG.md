# Changelog

All notable changes to NeuNote will be documented in this file.

The format is inspired by Keep a Changelog, and this project uses semantic versioning for formal releases.

## [1.1.0] - 2026-07-19

### Added

- Queue-wide and per-job pause, resume, retry, cancellation, and batch controls.
- Persistent job attempts, failure details, queue state, and restart recovery.
- Git sync inventory for paper records, source PDFs, extracted figures, chats, and broken references.
- Automatic Git rebase recovery and remote removal of optional PDF/chat data when sync is disabled.
- Focused tests for job scheduling, translation failures, PDF sync opt-in, and sync integrity.

### Changed

- Redesigned the frontend around a consistent Chinese retro letterpress style.
- Simplified navigation, library actions, paper-detail actions, and return behavior.
- Constrained dashboard catalogue panels to equal heights with internal scrolling.
- Improved enrichment translation completeness and made translation failures visible to the job scheduler.
- Expanded the jobs page with status summaries and multi-select operations.

### Fixed

- Prevented stale asynchronous paper requests from replacing the currently open paper.
- Preserved the latest paper state during translation and background refreshes.
- Improved queue scheduling consistency across pause, resume, cancellation, and application restarts.
- Fixed incomplete sync test coverage and invalid `unittest.mock` access.

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
