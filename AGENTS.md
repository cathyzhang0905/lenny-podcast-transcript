# Agent Instructions — lenny-podcast-transcript

> This file is read by Codex CLI / Cursor / Aider and other agents that follow the AGENTS.md convention. It tells the agent how to use this repo's tooling when the user asks for podcast transcripts.

## What this repo does

Translates YouTube podcast videos (default: Lenny's Podcast) into structured Markdown transcripts with speaker labels. Output language: `zh` (Chinese translation) / `en` (English with speakers) / `both`.

## When to invoke the tooling

Trigger when the user shares a YouTube URL **and** asks for a transcript / 中文逐字稿 / English transcript with speakers / digest source. Do NOT use for "summarize this" requests — this tool produces full verbatim transcripts, not summaries.

## How to invoke

```bash
# 1. Verify environment
test -f .venv/bin/activate || python3 -m venv .venv && source .venv/bin/activate
pip install -q -r requirements.txt
test -n "$AI_API_KEY" || echo "ERROR: export AI_API_KEY first" >&2

# 2. Run the CLI
python lenny_transcript.py --url "<YOUTUBE_URL>" --lang zh
# or: --lang en  (English with speaker tags only, no translation)
# or: --lang both  (writes <fname>.en.md and <fname>.zh.md, ~2x cost)
```

Override the auto-detected guest name when the title format is non-standard:

```bash
python lenny_transcript.py --url "..." --guest "Cat Wu" --lang zh
```

## Provider configuration

API key: `export AI_API_KEY=sk-...` — works with any OpenAI-compatible provider.

Default endpoint: `https://api.openai.com/v1` with `gpt-4o-mini`. To switch:

```bash
export AI_BASE_URL=https://api.deepseek.com    AI_MODEL=deepseek-chat
export AI_BASE_URL=https://api.siliconflow.cn/v1   AI_MODEL=Qwen/Qwen2.5-72B-Instruct
# Full provider list: see config.example.yaml
```

## Runtime expectations

- Single episode: **5-15 min** runtime per language
- Cost: typically **$0.05-2.00 USD per episode** depending on provider/model
- Output location: `./transcripts/<filename>.md` (or `.en.md` / `.zh.md` for `both`)
- Run in background if the agent supports it; foreground will block until complete

## Common issues

| Error | Cause | Fix |
|---|---|---|
| `RequestBlocked` | YouTube IP-throttled | Wait 30-60 min, try again, or change network |
| Wrong guest name in frontmatter | Title format doesn't match heuristics | Re-run with `--guest "Correct Name"` |
| Translation has wrong term (e.g., "Enthropic") | YouTube auto-caption ASR error | Add a line to `ASR_FIXES` in `lenny_transcript.py` |
| `RateLimitError` (429) | Provider TPM exhausted | Tool auto-retries with backoff (30s/60s/120s/240s). Wait. |

## File map

- `lenny_transcript.py` — single-URL CLI (start here)
- `watcher.py` — RSS-based channel monitor (auto dedup, batches new episodes)
- `config.yaml` — channel list + LLM provider + filename template (copy from `config.example.yaml`)
- `transcripts/` — output directory (auto-created)
- `skills/lenny-podcast-zh/SKILL.md` — same instructions but in Claude Code skill format

## What NOT to do

- Don't translate piecemeal manually; always invoke the CLI
- Don't try to fetch YouTube subtitles directly — the script does it via `youtube-transcript-api`
- Don't add summarization logic — this repo is for full transcripts only
