---
name: lenny-podcast-zh
description: Use when the user shares a YouTube URL of an interview-style podcast (especially Lenny's Podcast) and wants the FULL transcript with speaker labels — Chinese 中文逐字稿, English with speaker tags, or both. Triggers on phrases like "翻译成中文", "中文逐字稿", "中文 transcript", "把这个播客翻一下", "give me the English transcript with speakers", combined with a YouTube URL. Do NOT use for summary/digest requests — this skill produces full verbatim transcripts.
---

# lenny-podcast-zh

When invoked, run the lenny-podcast-transcript CLI to translate a YouTube podcast video into a Chinese transcript with speaker labels and YAML frontmatter.

## Required setup (verify before invoking)

1. Repo cloned somewhere on disk
2. Skill symlinked at `~/.claude/skills/lenny-podcast-zh` → resolves repo via `readlink`
3. `.venv` set up with `pip install -r requirements.txt`
4. Env var `AI_API_KEY` available (any OpenAI-compatible provider — OpenAI / DeepSeek / 硅基流动 / Moonshot / 智谱 / OpenRouter)

## Resolving repo path

The skill lives at `<REPO>/skills/lenny-podcast-zh` (two levels under repo root). To resolve repo root regardless of whether the user installed via `/plugin install` or symlinked manually:

```bash
SKILL_DIR=$(readlink -f ~/.claude/skills/lenny-podcast-zh 2>/dev/null || echo ~/.claude/skills/lenny-podcast-zh)
REPO=$(cd "$SKILL_DIR/../.." && pwd)
```

If the path can't be resolved, ask the user for the repo path explicitly.

If any of these are missing, instruct the user to set them up first — don't try to run the tool partially set up.

## How to use

1. **Confirm intent**: this skill is for full verbatim transcripts (~5-15 min runtime, cost varies by provider/model — typically $0.05-2.00 USD per episode). If the user wants a quick summary, defer.

2. **Get the YouTube URL** from the user message.

3. **Optionally guess the guest name** from the title — but the CLI auto-extracts it from the YouTube title in most cases. Only use `--guest "Name"` override if the title format is unusual.

4. **Pick output language** based on user intent:
   - User wants Chinese (default): `--lang zh`
   - User wants English with speakers: `--lang en`
   - User wants both: `--lang both` (writes `.en.md` and `.zh.md`)

5. **Run the CLI** via Bash:

   ```bash
   SKILL_DIR=$(readlink -f ~/.claude/skills/lenny-podcast-zh 2>/dev/null || echo ~/.claude/skills/lenny-podcast-zh)
   REPO=$(cd "$SKILL_DIR/../.." && pwd)
   cd "$REPO"
   source .venv/bin/activate
   python lenny_transcript.py --url "<YOUTUBE_URL>" --lang zh
   ```

   Run in `run_in_background: true` since processing takes 5-15 minutes per episode (×2 for `--lang both`). You'll get a completion notification.

5. **After completion**:
   - Read `transcripts/<filename>.md` to confirm output looks good
   - Show the user a quality preview (first 30 lines)
   - Offer to move/rename the file into their Obsidian vault

## Common issues to anticipate

- **`RequestBlocked` error**: YouTube IP-throttled the user's address (usually after multiple recent requests on the same video). Wait 30-60 minutes or change network. Don't retry immediately.
- **Wrong guest name**: The auto-extractor from title can fail on unusual title formats. Re-run with `--guest "Correct Name"` to override.
- **Translation quality**: Output is bound by YouTube auto-caption ASR quality. Common ASR errors are corrected by `ASR_FIXES` dict in `lenny_transcript.py`. New errors → user can add a line to that dict.

## Output format reference

```markdown
---
title: "..."
guest: "Cat Wu"
guest_company: "Lenny's Podcast"
date: 2026-04-23
video_id: PplmzlgE0kg
url: https://...
source: youtube-auto-captions
status: working-draft  # 工作稿,未经说话人审阅
---

# Cat Wu — How Anthropic's product team moves faster...

**Lenny**

你之前提到过......

**Cat Wu**

是的,我们的看法是......
```

## What this skill does NOT do

- ❌ Summary / digest (use a different tool/skill)
- ❌ Audio download / Whisper transcription (relies on YouTube auto-captions)
- ❌ Speaker diarization beyond LLM-inferred labels (~70-80% accuracy, occasional mislabels — manual fix in editor)
