# User Guide

NeuNote is organized around a few recurring workflows: collect papers, enrich them, review them, search notes, and chat with the library.

## Dashboard

The dashboard shows:

- library totals
- papers needing review
- recent reading activity
- duplicate candidates
- tag and author distributions

Use it as the daily starting point for continuing recent reading or checking library health.

## Literature Archive

Open `文献档案` to browse all papers.

Available actions:

- `归档新文献`: upload one or more PDFs.
- `刷新`: reload local library state.
- `批量整理`: enqueue enrichment for every paper that needs it.
- `校阅札记搜索`: search your review notes across the whole library.

Filters and sorting:

- search by title, author, venue, tags, abstract, or summary
- filter by reading status
- sort by newest added, year, or title
- filter by tag chips

## Paper Detail Page

The paper detail page has two columns.

Main column:

- key figures
- core concept definitions
- one-sentence summary
- research problem
- contributions
- method
- experiments
- limitations
- abstract

Key figures and core concepts are collapsed by default. Open them when you want the visual overview or glossary.

Side column:

- bibliography metadata
- author teams
- review notes
- tag management
- file metadata

`校阅札记` is the canonical place for your own short review notes. The older free-form side-note field is retained only for old YAML compatibility and is not exposed in the V1 UI.

## Enrichment

Click `重新整理` on a paper detail page, or `批量整理` in the archive.

Enrichment attempts to produce:

- structured bibliographic metadata
- author affiliations or teams
- 5-8 core concepts with plain-language definitions
- one-sentence summary
- research question
- contributions, methods, experiments, and limitations
- 1-3 key figures with extracted images and captions
- Chinese translations when configured

Jobs run in the background. Open `整理队列` to inspect progress, cancel one task, stop all active tasks, or clean finished jobs.

## Figure Extraction

Configure the extraction mode in Settings.

`快速识别`:

- uses Pillow to find colored figure regions
- expands crops with PyMuPDF text and drawing geometry
- faster and suitable for most papers
- agent chooses the important candidates and writes captions

`Agent 精裁`:

- gives the agent PyMuPDF tools for page rendering and crop saving
- slower
- useful for papers with unusual layouts or mostly monochrome figures

When `重新整理时重提取配图` is enabled, re-enrichment does not reuse old figure images.

## Bilingual Reading

The language button on a paper detail page switches between English and Chinese.

Chinese mode uses:

- translated summary fields
- translated core concepts with English concept names kept visible
- translated key-figure title/caption/reason with the original English shown as reference

For technical papers, use LLM translation for better terminology. Offline local translation is useful when privacy or network access is more important than translation quality.

## Review Note Search

Open `校阅札记搜索` from the literature archive.

The search page scans:

- review note text
- paper title
- authors
- tags
- venue and year

Results appear as cards with highlighted snippets. Click a card to open the corresponding paper detail page.

## Chat

Open `对话` from the navigation bar or `论文 Chat` from a paper detail page.

You can:

- ask about the whole library
- mention papers with `@`
- mention tags with `@`
- compare multiple papers
- ask for methods, experiments, limitations, or follow-up reading suggestions

Chat sessions are saved under `logs/chat_sessions/`. They are not synced unless you explicitly enable chat sync.

## Settings

Important settings:

- knowledge-base root
- Git sync mode and remote
- API endpoint, key, and model
- translation engine
- default detail-page language
- figure extraction mode
- enrichment concurrency

Settings are saved under the knowledge-base root in `metadata/app_config.yaml`. This file may contain credentials and should not be committed.

## Backup and Sync

Use Git sync for a private remote backup.

Recommended:

- keep source PDFs sync off unless the repository is private and large files are acceptable
- keep chat sync off unless you are comfortable syncing private discussion context
- use SSH or system credential helpers

Avoid:

- syncing to a public repository
- storing access tokens in the remote URL
- using the NeuNote source checkout as your knowledge-base root

## Data Ownership

NeuNote stores ordinary files. You can inspect, copy, back up, or edit them directly:

- paper records: `<kb-root>/papers/*.yaml`
- PDFs: `<kb-root>/originals/papers/*`
- figures: `<kb-root>/assets/paper_figures/*`
- chat sessions: `<kb-root>/logs/chat_sessions/*.json`

If you hand-edit YAML, keep field types stable. Run NeuNote afterward to let it normalize missing defaults.
