#!/usr/bin/env python3
"""把 YouTube 英文播客字幕处理成带说话人标注的 markdown(中文 / 英文 / 双语)。

调用方式:
  python lenny_transcript.py --url "https://www.youtube.com/watch?v=XXX"
  python lenny_transcript.py --url "..." --lang en          # 只输出英文
  python lenny_transcript.py --url "..." --lang both        # 同时输出 .en.md 和 .zh.md

输出包含 YAML frontmatter + 带说话人标注的正文。
"""

import argparse
import html as _html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date as _date
from pathlib import Path

from openai import OpenAI, RateLimitError
from youtube_transcript_api import YouTubeTranscriptApi

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
CHUNK_CHAR_LIMIT = 6000
HOST_NAME = "Lenny"

ASR_FIXES = [
    (r"\bcloud code\b", "Claude Code"),
    (r"\bcloud\.ai\b", "claude.ai"),
    (r"\bclawd\b", "Claude"),
    (r"\bEnthropic\b", "Anthropic"),
    (r"\bVerscell\b", "Vercel"),
    (r"\bReplet\b", "Replit"),
    (r"\bCat Woo\b", "Cat Wu"),
    (r"\blennisprobass\.com\b", "lennysnewsletter.com"),
    (r"\blenny.?s news\.com\b", "lennysnewsletter.com"),
    (r"\bopen claw\b", "OpenClaw"),
    (r"\bopen clauses\b", "OpenClaw"),
    (r"\bopen clauws\b", "OpenClaw"),
    (r"\bco-work\b", "Co-work"),
]


def _seed_line(host: str, last_speaker: str | None, lang: str) -> str:
    if lang == "zh":
        return (
            f"上一个 chunk 末尾说话人是 **{last_speaker}**,本 chunk 开头默认延续此说话人,直到从语境判断切换。"
            if last_speaker
            else f"第一个 chunk 通常以主持人 **{host}** 的开场白开始。"
        )
    return (
        f"The previous chunk ended with **{last_speaker}** speaking. Continue with this speaker by default until context indicates a switch."
        if last_speaker
        else f"The first chunk typically opens with the host **{host}** introducing the show."
    )


def _full_context_block(full_context: str | None, lang: str) -> str:
    if not full_context:
        return ""
    if lang == "zh":
        return f"""

完整 transcript 上下文(只供你判断 speaker 切换 / 对话节奏 / 整集结构,不要翻译这一段;只翻译 user message 给的那一段):

<full_transcript>
{full_context}
</full_transcript>"""
    return f"""

Full transcript context (use only to judge speaker turns / conversation flow / episode structure — do NOT label this; only label the chunk in the user message):

<full_transcript>
{full_context}
</full_transcript>"""


def system_prompt_zh(host: str, guest: str, last_speaker: str | None,
                     full_context: str | None = None) -> str:
    return f"""你是专业的播客翻译。把英文播客的逐字 transcript 翻译成自然的中文对话原文,并标注说话人。

主持人:{host}(host)
嘉宾:{guest}(guest)

翻译要求:
1. 忠实完整翻译,不要总结、不要省略
2. 保持口语对话语气
3. 重要产品名/公司名/技术术语/人名保留英文(例:Claude Code / Anthropic / RAG / PMF / OpenAI)
4. 不要加时间戳、章节标题、任何元信息

说话人标注要求:
5. 在每次说话人切换的地方,用一行 markdown 粗体标注:`**{host}**` 或 `**{guest}**`
6. 标注独占一行,前后各空一行
7. 通过语境判断说话人切换:谁在提问、谁在回答、自我介绍、提及"我们公司是 X"等线索
8. 一段话内不要切换说话人;不确定时延续当前说话人
9. {_seed_line(host, last_speaker, 'zh')}
10. 利用下方完整 transcript 上下文,推断出整集对话节奏(如 cold open 会出现金句剪辑 / Lenny 长篇 intro / 中段广告读稿等),让 speaker 切换判断更稳

输出要求:
11. 直接输出译文,前后不要加说明文字、引号、标题
12. 第一行就是说话人标注或正文{_full_context_block(full_context, 'zh')}"""


def system_prompt_en(host: str, guest: str, last_speaker: str | None,
                     full_context: str | None = None) -> str:
    return f"""You insert speaker labels into a podcast transcript. Do NOT translate. Output the original English text with speaker labels added.

Host: {host}
Guest: {guest}

Speaker labeling rules:
1. At every speaker change, insert a bold markdown label on its own line: `**{host}**` or `**{guest}**`
2. Each label sits on its own line with blank lines around it
3. Detect speaker changes from context: who is asking, who is answering, self-references like "we at <Company>", host's intro phrases
4. Do NOT split a single utterance across speakers; when uncertain, keep the current speaker
5. {_seed_line(host, last_speaker, 'en')}
6. Use the full transcript context below to understand the whole episode's pacing (cold open with quote-montages, host's long intro, mid-roll ad reads, etc.) to make speaker decisions more accurate.

Text rules:
7. Output the original English text verbatim — do not paraphrase, summarize, or translate
8. Preserve original wording, including filler words and natural speech
9. Do NOT add timestamps, section headers, or any meta-commentary
10. Output starts with a speaker label or text immediately — no preamble{_full_context_block(full_context, 'en')}"""


def system_prompt(host: str, guest: str, last_speaker: str | None,
                  lang: str = "zh", full_context: str | None = None) -> str:
    if lang == "en":
        return system_prompt_en(host, guest, last_speaker, full_context)
    return system_prompt_zh(host, guest, last_speaker, full_context)


def extract_video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|/embed/|/shorts/)([\w-]{11})", url)
    if not m:
        raise ValueError(f"无法从 URL 提取 video ID: {url}")
    return m.group(1)


def http_get(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def fetch_video_meta(video_id: str) -> dict:
    """返回 {title, author_name, upload_date}。失败时缺字段为 None。"""
    meta: dict = {"title": None, "author_name": None, "upload_date": None}
    try:
        oembed = json.loads(
            http_get(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            )
        )
        meta["title"] = oembed.get("title")
        meta["author_name"] = oembed.get("author_name")
    except Exception as e:
        print(f"      ⚠️ oembed 失败: {e}", file=sys.stderr)
    try:
        html = http_get(f"https://www.youtube.com/watch?v={video_id}")
        for pat in [
            r'"uploadDate":"(\d{4}-\d{2}-\d{2})',
            r'"datePublished":"(\d{4}-\d{2}-\d{2})',
            r'"dateCreated":"(\d{4}-\d{2}-\d{2})',
            r'itemprop="uploadDate"\s+content="(\d{4}-\d{2}-\d{2})',
            r'itemprop="datePublished"\s+content="(\d{4}-\d{2}-\d{2})',
        ]:
            m = re.search(pat, html)
            if m:
                meta["upload_date"] = m.group(1)
                break
    except Exception as e:
        print(f"      ⚠️ 抓 upload date 失败: {e}", file=sys.stderr)
    return meta


_NAME_PAT = r"[A-Z][a-zA-Z]+(?:[\s-][A-Z][a-zA-Z]+){1,3}"


def extract_guest(title: str, host: str = HOST_NAME) -> str | None:
    """从 YouTube 视频标题里启发式抽嘉宾名。Lenny's Podcast 标题常见格式:
       'topic | Guest Name (Title, Company)' / 'Guest, Company | topic' / 'topic with Guest'.
    """
    if not title:
        return None
    cleaned = re.sub(rf"\b{host}\b'?s?", "", title, flags=re.IGNORECASE)
    cleaned = re.sub(r"podcast", "", cleaned, flags=re.IGNORECASE)
    for pat in [
        rf"\|\s*({_NAME_PAT})\s*\(",        # "| Cat Wu (Head of...)"
        rf"\|\s*({_NAME_PAT})\s*[,|$]",     # "| Cat Wu, ..."
        rf"\|\s*({_NAME_PAT})\s*$",         # "...| Cat Wu"  (尾部)
        rf"\b({_NAME_PAT}),",                # "Cat Wu, Anthropic"
        rf"(?:with|featuring|ft\.?)\s+({_NAME_PAT})",  # "with Cat Wu"
        rf"[—–-]\s*({_NAME_PAT})\s*[,(|$]", # "— Cat Wu, ..."
    ]:
        m = re.search(pat, cleaned, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def slugify(text: str, max_len: int = 80) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    if len(text) > max_len:
        cut = text[:max_len].rsplit("-", 1)[0] or text[:max_len]
        text = cut
    return text


def format_filename(template: str, *, date: str, title: str, guest: str | None,
                    guest_company: str | None, video_id: str) -> str:
    return template.format(
        date=date or _date.today().isoformat(),
        title=slugify(title or video_id),
        guest=slugify(guest or "Guest", max_len=40),
        guest_company=slugify(guest_company or "", max_len=40),
        video_id=video_id,
    )


def apply_asr_fixes(text: str) -> str:
    for pattern, repl in ASR_FIXES:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text


def _looks_like_ip_block(err: Exception) -> bool:
    """Detect IP-block / rate-limit / bot-check errors from youtube-transcript-api."""
    msg = f"{type(err).__name__} {err}"
    return any(kw in msg for kw in (
        "RequestBlocked", "IpBlocked", "blocked",
        "Sign in to confirm", "bot", "429",
    ))


def _fetch_via_yta(video_id: str) -> str:
    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
    return " ".join(snippet.text for snippet in fetched)


def _parse_vtt(vtt: str) -> str:
    """Strip VTT timestamps/tags, dedupe rolling-text lines from auto-captions."""
    lines_out: list[str] = []
    for line in vtt.splitlines():
        line = line.strip()
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        if "-->" in line:
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and (not lines_out or lines_out[-1] != line):
            lines_out.append(line)
    text = _html.unescape(" ".join(lines_out))
    return re.sub(r"\s+", " ", text).strip()


def _fetch_via_ytdlp(video_id: str) -> str:
    """Fallback: yt-dlp + 浏览器 cookies。需要本机装了 yt-dlp 且对应浏览器登录过 YouTube。"""
    if not shutil.which("yt-dlp"):
        raise RuntimeError(
            "yt-dlp 未安装(fallback 路径需要)。pip install yt-dlp 后重试。"
        )
    browser = os.environ.get("YT_DLP_COOKIES_BROWSER", "chrome")
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [
                "yt-dlp", "--quiet",
                "--skip-download", "--write-auto-sub",
                "--sub-lang", "en", "--sub-format", "vtt",
                "--cookies-from-browser", browser,
                "-o", f"{tmp}/%(id)s.%(ext)s",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"yt-dlp 失败 (browser={browser}):\n{result.stderr[-600:]}\n"
                f"提示:确认 {browser} 已登录 YouTube;或设 env YT_DLP_COOKIES_BROWSER=firefox/safari/edge 切换"
            )
        vtt_files = list(Path(tmp).glob("*.vtt"))
        if not vtt_files:
            raise RuntimeError(f"yt-dlp 跑成功但没产出 .vtt 文件;stderr={result.stderr[-400:]}")
        return _parse_vtt(vtt_files[0].read_text(encoding="utf-8"))


def fetch_transcript_en(video_id: str, allow_fallback: bool = True) -> str:
    """主路径走 youtube-transcript-api;撞 IP block 时自动 fallback 到 yt-dlp + 浏览器 cookies。

    需禁用 fallback(用于测试)时传 allow_fallback=False。
    """
    try:
        text = _fetch_via_yta(video_id)
    except Exception as e:
        if allow_fallback and _looks_like_ip_block(e):
            print(f"      ⚠️ 主路径被 block ({type(e).__name__}),fallback 到 yt-dlp + 浏览器 cookies...")
            text = _fetch_via_ytdlp(video_id)
        else:
            raise
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r">>\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return apply_asr_fixes(text)


def chunk_by_sentence(text: str, limit: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, buf, cur = [], [], 0
    for s in sentences:
        if cur + len(s) > limit and buf:
            chunks.append(" ".join(buf))
            buf, cur = [], 0
        buf.append(s)
        cur += len(s) + 1
    if buf:
        chunks.append(" ".join(buf))
    return chunks


def detect_last_speaker(zh: str, host: str, guest: str) -> str | None:
    """从已翻译的中文片段末尾找最近的说话人标注。"""
    pattern = re.compile(rf"\*\*({re.escape(host)}|{re.escape(guest)})\*\*")
    matches = pattern.findall(zh)
    return matches[-1] if matches else None


def translate_chunk(client: OpenAI, model: str, chunk: str, host: str,
                    guest: str, last_speaker: str | None, lang: str = "zh",
                    full_context: str | None = None, max_retries: int = 4) -> str:
    """带 429 退避重试。等待序列 30/60/120/240s,共最多 ~7 分钟。"""
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=8192,
                temperature=0.3,
                messages=[
                    {"role": "system",
                     "content": system_prompt(host, guest, last_speaker, lang, full_context)},
                    {"role": "user", "content": chunk},
                ],
            )
            return (resp.choices[0].message.content or "").strip()
        except RateLimitError as e:
            last_err = e
            wait = 30 * (2 ** attempt)
            print(f"      ⚠️ 429 rate limit (attempt {attempt+1}/{max_retries}),sleep {wait}s 后重试")
            time.sleep(wait)
    raise last_err if last_err else RuntimeError("translate_chunk: unexpected fallthrough")


def process_with_speakers(client: OpenAI, model: str, en_text: str,
                          host: str, guest: str, lang: str = "zh",
                          full_context: bool = True) -> str:
    """lang='zh' 翻译并加 speaker 标注;'en' 仅在原文上加 speaker 标注。
    full_context=True 时,每个 chunk 的 system prompt 携带完整英文 transcript,
    LLM 能看到整集对话结构,speaker 标注精度显著提升。"""
    chunks = chunk_by_sentence(en_text, CHUNK_CHAR_LIMIT)
    action = "翻译" if lang == "zh" else "标注 speaker"
    ctx_note = "+全文上下文" if full_context else "(局部上下文)"
    print(f"      {action} {len(chunks)} 块 {ctx_note} (model={model}, lang={lang})")
    full_ctx = en_text if full_context else None
    pace = 8 if full_context else 0   # full-context 模式下每次调用间 sleep,避免撞 TPM
    parts: list[str] = []
    last_speaker: str | None = None
    for i, ch in enumerate(chunks, 1):
        if i > 1 and pace:
            time.sleep(pace)
        print(f"      [{i}/{len(chunks)}] {len(ch):,} 字符 → 处理中…")
        out = translate_chunk(client, model, ch, host, guest, last_speaker, lang, full_ctx)
        parts.append(out)
        last_speaker = detect_last_speaker(out, host, guest) or last_speaker
    return "\n\n".join(parts)


# 向后兼容
translate_with_speakers = process_with_speakers


def build_frontmatter(*, title: str | None, guest: str | None,
                      guest_company: str | None, date: str | None,
                      video_id: str, url: str, lang: str = "zh") -> str:
    def esc(v: str) -> str:
        return v.replace('"', '\\"')
    lines = ["---"]
    if title:
        lines.append(f'title: "{esc(title)}"')
    if guest:
        lines.append(f'guest: "{esc(guest)}"')
    if guest_company:
        lines.append(f'guest_company: "{esc(guest_company)}"')
    lines.append(f"date: {date or _date.today().isoformat()}")
    lines.append(f"video_id: {video_id}")
    lines.append(f"url: {url}")
    lines.append(f"lang: {lang}")
    lines.append("source: youtube-auto-captions")
    lines.append("status: working-draft")
    lines.append("---")
    return "\n".join(lines)


def write_episode(out_path: Path, frontmatter: str, h1_title: str, body: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        f"{frontmatter}\n\n# {h1_title}\n\n{body.strip()}\n",
        encoding="utf-8",
    )


def _resolve_langs(lang: str) -> list[str]:
    if lang == "both":
        return ["en", "zh"]
    if lang in ("en", "zh"):
        return [lang]
    raise ValueError(f"unknown lang: {lang}")


def _output_path(out_dir: Path, fname: str, lang: str, multi: bool) -> Path:
    return out_dir / (f"{fname}.{lang}.md" if multi else f"{fname}.md")


def run_url(client: OpenAI, model: str, url: str, out_dir: Path,
            filename_template: str, override_guest: str | None,
            override_title: str | None, lang: str = "zh") -> None:
    vid = extract_video_id(url)
    print(f"[1/4] 拉视频元信息: {vid}")
    meta = fetch_video_meta(vid)
    title = override_title or meta.get("title") or vid
    guest = override_guest or extract_guest(title) or "Guest"
    upload_date = meta.get("upload_date") or _date.today().isoformat()
    print(f"      title={title!r}")
    print(f"      guest={guest!r}  date={upload_date}")

    print(f"[2/4] 拉字幕")
    en = fetch_transcript_en(vid)
    print(f"      英文 {len(en):,} 字符")

    langs = _resolve_langs(lang)
    multi = len(langs) > 1
    fname = format_filename(
        filename_template, date=upload_date, title=title, guest=guest,
        guest_company=meta.get("author_name"), video_id=vid,
    )
    h1 = f"{guest} — {title}" if title and title != vid else (title or vid)

    for li, lg in enumerate(langs, 1):
        print(f"[3/4] ({li}/{len(langs)}) {'翻译 + ' if lg == 'zh' else ''}说话人标注 (lang={lg})")
        body = process_with_speakers(client, model, en, HOST_NAME, guest, lg)
        out_path = _output_path(out_dir, fname, lg, multi)
        fm = build_frontmatter(
            title=title, guest=guest, guest_company=meta.get("author_name"),
            date=upload_date, video_id=vid, url=url, lang=lg,
        )
        write_episode(out_path, fm, h1, body)
        print(f"[4/4] ✓ {out_path}")


def split_frontmatter(md_text: str) -> tuple[str, str]:
    if md_text.startswith("---\n"):
        end = md_text.find("\n---\n", 4)
        if end != -1:
            return md_text[: end + 5], md_text[end + 5 :]
    return "", md_text


def run_file(client: OpenAI, model: str, path: Path, out_dir: Path,
             filename_template: str, override_guest: str | None,
             override_title: str | None, lang: str = "zh") -> None:
    print(f"[1/3] 读文件: {path}")
    raw = path.read_text(encoding="utf-8")
    fm_in, body_in = split_frontmatter(raw)
    print(f"      正文 {len(body_in):,} 字符 (frontmatter {'有' if fm_in else '无'})")

    title = override_title or path.stem
    guest = override_guest or "Guest"
    langs = _resolve_langs(lang)
    multi = len(langs) > 1

    fname = format_filename(
        filename_template, date=_date.today().isoformat(),
        title=override_title or path.stem, guest=guest,
        guest_company=None, video_id="local",
    )

    for li, lg in enumerate(langs, 1):
        print(f"[2/3] ({li}/{len(langs)}) 处理 lang={lg}")
        body = process_with_speakers(client, model, body_in.strip(), HOST_NAME, guest, lg)
        out_path = _output_path(out_dir, fname, lg, multi)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if fm_in and not multi:
            out_path.write_text(f"{fm_in.rstrip()}\n\n{body.strip()}\n", encoding="utf-8")
        else:
            fm_new = build_frontmatter(
                title=title, guest=guest, guest_company=None,
                date=None, video_id="local", url=str(path), lang=lg,
            )
            write_episode(out_path, fm_new, title, body)
        print(f"[3/3] ✓ {out_path}")


def main() -> int:
    p = argparse.ArgumentParser(description="英文播客 transcript → 中文(带说话人)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="YouTube 视频 URL")
    src.add_argument("--file", help="本地英文 md 文件路径")
    p.add_argument("--out", default="./transcripts", help="输出目录(默认 ./transcripts)")
    p.add_argument("--guest", default=None, help="覆盖嘉宾名(标题抽不准时手动指定)")
    p.add_argument("--title", default=None, help="覆盖标题")
    p.add_argument("--base-url", default=os.environ.get("AI_BASE_URL", DEFAULT_BASE_URL),
                   help="OpenAI 兼容协议 endpoint(env: AI_BASE_URL)")
    p.add_argument("--model", default=os.environ.get("AI_MODEL", DEFAULT_MODEL),
                   help="模型 ID(env: AI_MODEL)")
    p.add_argument(
        "--filename-template",
        default="{date}_{title}",
        help="文件名模板,占位符:{date} {title} {guest} {guest_company} {video_id}",
    )
    p.add_argument(
        "--lang",
        default=os.environ.get("OUTPUT_LANG", "zh"),
        choices=["zh", "en", "both"],
        help="输出语言:zh(中文翻译,默认)/ en(英文 + speaker)/ both(双语两个文件)",
    )
    args = p.parse_args()

    api_key = os.environ.get("AI_API_KEY")
    if not api_key:
        print("错误:请先 export AI_API_KEY=...", file=sys.stderr)
        return 1

    client = OpenAI(api_key=api_key, base_url=args.base_url)
    out_dir = Path(args.out)

    if args.url:
        run_url(client, args.model, args.url, out_dir, args.filename_template,
                args.guest, args.title, args.lang)
    else:
        run_file(client, args.model, Path(args.file), out_dir,
                 args.filename_template, args.guest, args.title, args.lang)
    return 0


if __name__ == "__main__":
    sys.exit(main())
