# Agent Guide

One YAML file per paper under `papers/`. Source PDFs live in `originals/papers/`.

## Read path

1. List papers: scan `papers/` directory.
2. Read one paper: open `papers/<paper_id>.yaml`.
3. Evidence check only: open `originals/papers/<paper>.pdf`.

## Write rules

- Create / update / delete **only** `papers/<paper_id>.yaml`.
- Never write to `originals/papers/` except during upload.
- Log significant changes to `logs/update_log.md`.

## Paper YAML schema

Each `papers/<id>.yaml` contains:

```yaml
id: paper_id
title: "Paper Title"
authors: [Author One, Author Two]
year: 2025
venue: "Conference Name"
doi: ""
arxiv_id: ""
source_pdf: originals/papers/paper.pdf
pages: 12
tags: [anomaly_detection, time_series]
status: profiled
confidence: medium
reading_status: unread
priority: normal
needs_review: true

abstract: "..."
one_sentence: "..."
problem: "..."
contributions: [...]
method: [...]
experiments: [...]
limitations: [...]

notes: |
  # Markdown notes
  Free-form reading notes...

review_notes: [...]
agent_reviews: [...]
created_at: "2026-..."
updated_at: "2026-..."
```
