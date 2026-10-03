# reel-analyzer

Gave ai the ability to watch reels. Why? your guess is as good as mine.

An MCP server that watches a short-form video so the calling model doesn't have to.

Paste an Instagram Reel / TikTok / YouTube link into a chat, the main model calls one
tool, and it gets back a plain-text block: what was **said** (Whisper) and what was
**shown** (a vision model reading extracted frames). The main model never sees the
specialist models — it just gets tool output.

```
analyze_video(url_or_path: str) -> str
```

## How it works

Acquire the clip once, then run two independent legs in parallel:

- **Leg A — words out.** ffmpeg strips the audio track; Whisper transcribes it via
  OpenRouter. A silent clip returns `(no audio)`, which is a success, not an error.
- **Leg B — watch it.** ffmpeg samples frames at every scene cut *plus* a steady
  ~2fps floor, downscales them, and sends them as base64 images to a vision model.
  It describes the action and transcribes every on-screen caption verbatim.

Frame sampling is the default because short-form video is fast-paced: native video
input samples at ~1fps and misses hard cuts and captions that flash for under a
second. Set `FEED_MODE=video` to send the whole clip instead.

If one leg fails the other still returns. Only a failure of **both** is an error.

| Leg A | Leg B | Result |
|---|---|---|
| ok | ok | full two-section output |
| `(no audio)` | ok | visual description + `(no audio)` — success |
| ok | fail | transcript + `(visual analysis failed: …)` |
| fail | ok | `(transcription failed: …)` + visual description |
| fail | fail | readable error |

## Prerequisites

- Python 3.11+
- `ffmpeg` and `ffprobe` on PATH — `brew install ffmpeg`
- An [OpenRouter](https://openrouter.ai) API key

## Install

```bash
git clone git@github.com:lionel509/Reel-analyzer.git
cd Reel-analyzer
UV_PROJECT_ENVIRONMENT=~/.venvs/reel-analyzer uv sync
cp .env.example .env    # then fill in OPENROUTER_API_KEY
```

The virtualenv deliberately lives **outside** the project directory
(`~/.venvs/reel-analyzer`) — the checkout doubles as a folder inside an Obsidian
vault, and Obsidian should never index a venv.

## Smoke test — the dev loop

Runs the exact pipeline the MCP tool runs, without a host in the way:

```bash
~/.venvs/reel-analyzer/bin/python -m reel_analyzer.smoke <url_or_path> -v
```

Exits non-zero only if both legs fail.

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | **required**, auth |
| `TRANSCRIPTION_MODEL` | `openai/whisper-large-v3` | Leg A model. `openai/whisper-1` and `gpt-4o-mini-transcribe` return 403 on OpenRouter |
| `VISION_MODEL` | `google/gemma-4-26b-a4b-it` | Leg B model; bump to `google/gemma-4-31b-it` if captions read poorly |
| `FEED_MODE` | `frames` | `frames` (extract our own) or `video` (send the clip, ~1fps) |
| `SCENE_THRESHOLD` | `0.3` | ffmpeg scene score for a hard cut; lower = more frames |
| `UNIFORM_FPS` | `2.0` | steady sampling floor for mid-scene caption changes |
| `FRAME_MIN_GAP` | `0.4` | seconds; collapses a cut and a uniform tick landing together |
| `MAX_FRAMES` | `40` | hard cap; the output notes when it bites |
| `FRAME_LONG_EDGE` | `768` | downscale before encoding |
| `FRAME_QUALITY` | `3` | ffmpeg `-q:v` |
| `MAX_DURATION_SECONDS` | `900` | guard against accidentally analysing a feature film |
| `AUDIO_TIMEOUT` | `120` | Leg A read timeout |
| `VISION_TIMEOUT` | `240` | Leg B read timeout |
| `DOWNLOAD_TIMEOUT` | `300` | yt-dlp timeout |
| `MAX_RETRIES` | `4` | attempts on 429 / 5xx, with backoff |
| `INSTAGRAM_COOKIES_FILE` | — | Netscape cookies export, for private or rate-limited reels |
| `OPENROUTER_REFERER` / `OPENROUTER_TITLE` | — | label the calls in the OpenRouter dashboard |

## Host registration

Standard `mcpServers` block — the same shape Cherry Studio, Claude Desktop, and
Claude Code all use:

```json
{
  "mcpServers": {
    "reel-analyzer": {
      "type": "stdio",
      "command": "/Users/YOU/.venvs/reel-analyzer/bin/python",
      "args": ["-m", "reel_analyzer.server"],
      "env": {
        "OPENROUTER_API_KEY": "sk-or-..."
      }
    }
  }
}
```

**Cherry Studio:** Settings → MCP Servers → Add Server → type `STDIO`, then the
command/args/env above.

**Obsidian:** via the Smart Composer plugin, which acts as an MCP *client*. Same
stdio config. Verify the exact field names against the plugin's current settings.

**Claude Code:**

```bash
claude mcp add reel-analyzer -- ~/.venvs/reel-analyzer/bin/python -m reel_analyzer.server
```

## Worked example

<!-- Paste real `analyze_video` output here after the first successful run. -->
_Pending the first real run against a live reel._

## Troubleshooting

**"this reel requires login cookies"** — Instagram gated the post. Export cookies
from a logged-in browser session in Netscape format and point
`INSTAGRAM_COOKIES_FILE` at the file.

**"the platform rate-limited this request"** — transient. Wait and retry; cookies
also raise the limit.

**Captions read inaccurately** — raise `UNIFORM_FPS` and `MAX_FRAMES`, or switch
`VISION_MODEL` to `google/gemma-4-31b-it` (denser, ~2× the price, stronger at
reading text in a single image).

**Output includes a frame-cap note** — sampling hit `MAX_FRAMES` and skipped
frames. Raise the cap for denser coverage; it is never silently truncated.

**yt-dlp fails on a site that used to work** — platforms change constantly.
`uv sync --upgrade-package yt-dlp`.

## Cleanup

Teardown when this checkout is done: see [`CLEANUP.md`](CLEANUP.md) — what the
pipeline leaves behind, preview/clean commands (they keep `.env`, cookies and the
gitignored `Reel Analyzer MCP — *.md` hub notes), and the outside-the-repo bits
(`~/.venvs/reel-analyzer`, `~/.config/reel-analyzer/config.json`, yt-dlp's cache).
