# Knowledge Base

NeuNote stores a library as ordinary files. The default development root is the repository root, but users can select any folder from Settings.

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
```

Do not commit this file when it contains private keys or local paths.
