# Knowledge Base

NeuNote stores a library as ordinary files in an independent data root. The default is `~/.neunote`; users can select another folder from Settings. Do not place the knowledge base inside the NeuNote source repository or another Git work tree.

## Folder Layout

```text
<kb-root>/
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

## Paper Records

Each paper is stored as `papers/<paper_id>.yaml`. Common fields include:

```yaml
id: example_paper
title: Example Paper
authors:
  - Ada Lovelace
year: 2026
venue: arXiv
doi: ""
arxiv_id: ""
source_pdf: originals/papers/example.pdf
pages: 12
tags:
  - llm
status: profiled
confidence: medium
reading_status: unread
priority: normal
needs_review: false
abstract: ""
one_sentence: ""
problem: ""
contributions: []
method: []
experiments: []
limitations: []
notes: ""
review_notes: []
translations: {}
created_at: "2026-06-14T00:00:00+00:00"
updated_at: "2026-06-14T00:00:00+00:00"
```

Fields are intentionally explicit so both humans and agents can review them. Missing or unknown values should remain empty rather than invented.

## Source PDFs

Source PDFs live in `originals/papers/` and are referenced by `source_pdf`. They are ignored by git by default because they are often large and may be copyrighted.

## Chat Sessions

Chat sessions are stored as one JSON file per conversation in `logs/chat_sessions/`.

Each session contains:

- `id`
- `title`
- `created_at`
- `updated_at`
- optional top-level `paper_ids`
- `messages`

User messages may contain `paper_ids`, representing the papers mentioned for that turn. Assistant messages may contain ordered `segments` so text and tool calls can be replayed in the same order they streamed.

## Runtime Configuration

`metadata/app_config.yaml` stores local settings such as:

```yaml
claude_api_key: ""
claude_endpoint: ""
claude_model: sonnet
max_concurrency: 4
translation_engine: local
sync_mode: local
git_auto_sync: false
git_sync_interval_minutes: 10
```

Do not commit this file when it contains private keys or local paths.

## User Data and Sync Boundaries

NeuNote classifies stored data as follows:

| Path | Classification | Git sync |
| --- | --- | --- |
| `papers/*.yaml` | Core user library data: notes, tags, reading state, summaries | Always included when Git sync is enabled |
| `logs/chat_sessions/*.json` | User conversations and research context | Optional, off by default |
| `originals/papers/*` | User-provided source documents | Optional, off by default |
| `metadata/app_config.yaml` | Local configuration and API credentials | Never included |
| `.kb_app_config.yaml` | Machine-local root selection | Never included |
| `logs/jobs/`, `logs/debug/`, ingest/update logs | Ephemeral operational data | Never included |

Git sync exposes an **立即同步** action and an optional backend schedule. Scheduled sync is disabled by default; its interval defaults to 10 minutes and can be set from 1 to 1440 minutes. The knowledge-base folder becomes its own Git repository; an existing remote branch is fetched into an empty knowledge base on first sync. Local-only mode does not invoke Git or access a network. Git credentials are handled by the user's existing SSH agent or Git credential helper.
