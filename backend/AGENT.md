# Agent Guide

One YAML file per paper under `papers/`.  Source PDFs live in `originals/papers/`.

Paper records may be metadata-only. `pdf_url` is remote metadata; only a validated local `source_pdf` may use `download_status: downloaded`. Full-text retrieval requires `index_status: indexed`.

## Read path

1. List papers: scan `papers/` directory.
2. Read one paper: open `papers/<paper_id>.yaml`.
3. Evidence check only: open `originals/papers/<paper>.pdf`.

## Write rules

- Create / update / delete **only** `papers/<paper_id>.yaml`.
- Never write to `originals/papers/` except during upload.
- Log significant changes to `logs/update_log.md`.
