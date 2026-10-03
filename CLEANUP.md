# Cleanup — `lionel509/Reel-analyzer`

Teardown for this checkout. **reel-analyzer** is an MCP server that acquires a
short-form clip (yt-dlp + ffmpeg), runs a Whisper leg and a vision leg through
OpenRouter, and hands the model back plain text. It is Python (`src/reel_analyzer/`,
installed with uv) plus an Obsidian plugin subfolder (`obsidian-plugin/`, esbuild +
TypeScript). Nothing here is deleted by the commands below unless it is ignored —
no tracked file is touched.

## ⚠ What must NOT be cleaned

| Path | Why it stays |
| --- | --- |
| `/Reel Analyzer MCP — *.md` | **gitignored hub notes.** This checkout doubles as a folder in an Obsidian vault; those notes are the local record. Ignored ≠ disposable — the clean commands below carry an explicit `-e` so they are never removed. |
| `obsidian-plugin/main.js` | the **built** plugin, committed on purpose — Obsidian loads it off disk. Tracked, so `git clean` cannot touch it; if a rebuild dirties it, restore it, don't delete it. |
| `uv.lock` | dependency lock; never ignore it, never clean it |
| `src/`, `pyproject.toml`, `.env.example` | source, manifest, the documented env template (`.env.*` is ignored **with `!.env.example`** so the template survives) |
| `.env`, `cookies.txt` | secrets — kept on purpose, see **Secrets** |

## What this project leaves behind

| Path / thing | Created by | Size note |
| --- | --- | --- |
| `.env` | `cp .env.example .env` per the README Install — holds a **real `OPENROUTER_API_KEY`** | bytes; ignored, kept |
| `cookies.txt` / `*.cookies.txt` | the Netscape cookie export `INSTAGRAM_COOKIES_FILE` points at | bytes; ignored, kept — session cookies, same class as a key |
| `obsidian-plugin/node_modules/` | `npm install` / `npm ci` in `obsidian-plugin/` | ~50–150 MB (esbuild + typescript + obsidian types) |
| `obsidian-plugin/*.tsbuildinfo`, `coverage/` | a hand-run `tsc` or coverage run | KBs |
| `__pycache__/`, `*.pyc` | importing `reel_analyzer` | KBs |
| `venv/`, `.venv/`, `env/` | only if someone venvs **in-tree** — the README's install deliberately puts it at `~/.venvs/reel-analyzer` instead | ~50–100 MB if present |
| `*.egg-info/`, `build/`, `dist/` | a stray `pip install -e .` (build backend here is hatchling) | < 1 MB |
| `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.coverage`, `htmlcov/` | hand-run validators — no test suite is configured yet | KBs |
| `/graphify-out/`, `/.graphifyignore` | the code-graph tool run over this tree | MBs |
| `.env.*` (other than `.env.example`) | a copied env variant (`.env.local`, `.env.production`) | bytes |
| `.idea/`, `.vscode/`, `*.swp`, `.DS_Store`, `.claude/settings.local.json` | editors / macOS / Claude Code | bytes |
| `*.log`, `logs/` | anything that logs into the tree | KBs |

`pipeline.py`'s workdir (`tempfile.TemporaryDirectory(prefix="reel-analyzer-")`) and
ffmpeg's temp files live in the **system temp dir**, not the repo, and are removed
on exit.

## Preview

```bash
git clean -ndX -e '!.env' -e '!.env.*' -e '!/Reel Analyzer MCP — *.md'
```

## Clean the repo

```bash
git clean -fdX -e '!.env' -e '!.env.*' -e '!/Reel Analyzer MCP — *.md'
```

The `-e` flags are load-bearing:

- `-e '!.env' -e '!.env.*'` — keeps your key and any env variants.
- `-e '!/Reel Analyzer MCP — *.md'` — keeps the gitignored hub notes. Without it
  those notes are ignored-and-deleted in one shot, which is exactly the trap.

If `obsidian-plugin/node_modules/` was the point, the repo-wide command above
already gets it (the stock block has `node_modules/`). Nothing extra to run.

```bash
git status --short    # must show no tracked file modified or deleted
```

## Outside the repo

Everything here is **real, and specific to this project**. Nothing is shared with
other repos except where noted.

**The uv virtualenv — this project only:**

```bash
du -sh ~/.venvs/reel-analyzer 2>/dev/null || echo "not installed"
rm -rf ~/.venvs/reel-analyzer
```

**The settings file `reel-analyzer-configure` writes — holds the API key, mode 600:**

```bash
rm -f ~/.config/reel-analyzer/config.json
```

**yt-dlp's cache — shared with every yt-dlp install on the machine:**

```bash
du -sh ~/.cache/yt-dlp 2>/dev/null
rm -rf ~/.cache/yt-dlp          # shared — optional
```

**Orphaned pipeline workdirs** (normally auto-removed; a killed run can leave one):

```bash
find "${TMPDIR:-/tmp}" -maxdepth 1 -name 'reel-analyzer-*' -print
find "${TMPDIR:-/tmp}" -maxdepth 1 -name 'reel-analyzer-*' -mtime +1 -exec rm -rf {} +
```

**The plugin as installed into the Obsidian vault** (`install.mjs` copies
`main.js`, `manifest.json`, `styles.css` to `$OBSIDIAN_VAULT/.obsidian/plugins/reel-analyzer`,
default vault `~/Documents`):

```bash
ls -la "${OBSIDIAN_VAULT:-$HOME/Documents}/.obsidian/plugins/reel-analyzer" 2>/dev/null
rm -rf "${OBSIDIAN_VAULT:-$HOME/Documents}/.obsidian/plugins/reel-analyzer"   # only if you mean to uninstall the plugin
```

Removing it means re-enabling the plugin next time; the source of truth stays in
`obsidian-plugin/`.

**npm's cache** from `npm install` — shared across every node project:

```bash
npm cache verify          # preview
npm cache clean --force   # shared — optional
```

**`brew install ffmpeg`** — shared with everything else on this Mac. Do **not**
uninstall it for this repo.

**Nothing else outside the repo.** No Playwright browsers, no Docker images, no
launchd plists, no model caches — frames and audio go straight to OpenRouter and
are not cached locally.

## Secrets

`.env`, `.env.*` (other than the tracked `.env.example`), `cookies.txt`,
`*.cookies.txt`, `*.key`, `*.pem`, `credentials.json`, `secrets.json` and
`client_secret*.json` are **ignored and kept** by every command above — the
`-e '!.env' -e '!.env.*'` flags exist for this and must not be dropped. The
`.config/reel-analyzer/config.json` file is outside the repo entirely.

To destroy local credentials you have to mean it — git will not do it for you:

```bash
rm -f .env .env.local cookies.txt *.cookies.txt
rm -f ~/.config/reel-analyzer/config.json
```

If a key ever *does* get committed, rotate it on OpenRouter first and open an
issue — this repo has no gitleaks hook, so nothing here would have caught it.
