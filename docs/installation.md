# Installation and Setup

This guide takes a fresh clone from zero to a working NeuNote library.

## 1. Install System Requirements

NeuNote needs Python, Bun, uv, and Poppler.

macOS:

```bash
brew install python@3.11 bun uv poppler
```

Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv poppler-utils
curl -fsSL https://bun.sh/install | bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Confirm the tools are available:

```bash
python3 --version
bun --version
uv --version
pdftoppm -v
```

## 2. Clone and Install Dependencies

```bash
git clone <repo-url> neunote
cd neunote

bun install
cd frontend
bun install
cd ../backend
uv sync
cd ..
```

The repository does not include user library data. NeuNote creates a knowledge-base folder on first launch.

Optional local environment overrides:

```bash
cp .env.example .env
```

The root dev runner reads `.env` if present. Do not commit `.env`.

## 3. Start the App

```bash
bun run dev
```

Open http://127.0.0.1:5173.

The root dev runner starts:

- FastAPI backend on http://127.0.0.1:8765
- Vite frontend on http://127.0.0.1:5173
- Knowledge-base root at `~/.neunote`, unless `KB_DEFAULT_ROOT` is set

## 4. Choose a Knowledge-Base Root

Use Settings to choose where NeuNote stores your library.

Recommended:

```text
~/.neunote
~/Documents/NeuNoteLibrary
~/Research/neunote-library
```

Avoid:

```text
<the NeuNote source checkout>
any folder inside another Git repository
shared folders that sync partial files while NeuNote is writing
```

The knowledge base contains personal data. Keep it separate from the app source repository.

## 5. Configure Enrichment and Translation

NeuNote can run without an API key, but agent enrichment and LLM translation need an Anthropic-compatible endpoint.

In Settings, configure:

- Agent API endpoint: optional; leave blank for Anthropic's default endpoint
- API key: stored only in `metadata/app_config.yaml` under your knowledge-base root
- Model: for example `sonnet` or the model name supported by your compatible endpoint
- Translation engine: `LLM service` for best technical translations, `local model` for offline Argos translation
- Figure extraction mode:
  - `Fast recognition`: faster Pillow-based region detection; agent selects candidates and writes captions
  - `Agent precise crop`: slower PyMuPDF tool flow for difficult layouts

## 6. Upload and Enrich Papers

1. Open the dashboard or literature archive.
2. Click `归档新文献`.
3. Select one or more PDFs.
4. Open a paper detail page and click `重新整理`, or use `批量整理` from the literature archive.
5. Track progress in `整理队列`.

Generated enrichment is stored in each paper YAML. Extracted key-figure images are stored in `assets/paper_figures/`.

## 7. Optional Git Sync

Git sync is configured from Settings.

Modes:

- `Local only`: no Git commands are run.
- `Git sync`: NeuNote treats the selected knowledge-base root as its own Git repository.

Synced by default:

- `papers/*.yaml`
- `assets/paper_figures/*`

Optional:

- chat sessions
- source PDFs

Never synced:

- API keys
- machine-local app config
- job logs
- debug logs

First sync to a new private remote:

1. Create an empty GitHub repository.
2. Copy its SSH or HTTPS URL.
3. In NeuNote Settings, select `Git sync`.
4. Fill remote name, branch, and remote URL.
5. Click `保存设置`.
6. Click `立即同步`.

Use SSH keys or your system Git credential helper. Do not put access tokens in the remote URL.

## 8. Production-Like Local Run

Build the frontend:

```bash
bun run build
```

Run backend checks and tests:

```bash
bun run check
```

For a long-running local backend:

```bash
cd backend
KB_DEFAULT_ROOT="$HOME/.neunote" uv run uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Serve `frontend/dist` with your preferred static file server or keep using Vite for local workflows.

## Troubleshooting

`pdftoppm` not found:

- Install Poppler.
- Restart the terminal so the command is on `PATH`.

Argos translation is slow on first run:

- The first local translation may download and initialize the offline model.
- Use LLM translation for better technical term handling.

Enrichment does not start:

- Check Settings for API key/model configuration.
- Open `整理队列` for job status.
- Inspect logs under `<kb-root>/logs/debug/` if running a development build.

Git sync fails on first run:

- Ensure the knowledge-base root is not inside this source repository.
- Confirm the remote URL is reachable from normal `git` commands.
- Configure SSH keys or Git credential helper outside NeuNote.

Images appear stale after enrichment:

- Reload the paper detail page. NeuNote version-tags figure URLs with the paper update timestamp so new enrichment should bypass browser cache automatically.
