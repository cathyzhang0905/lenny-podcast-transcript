#!/usr/bin/env python3
"""把 YouTube 英文播客字幕翻译成带说话人标注的中文 markdown。

调用方式:
  python lenny_transcript.py --url "https://www.youtube.com/watch?v=XXX"
  python lenny_transcript.py --file path/to/english.md --guest "Cat Wu"

输出包含 YAML frontmatter + 带说话人标注的中文正文。
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date as _date
from pathlib import Path

from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi

BASE_URL = "https://api.siliconflow.cn/v1"
MODEL = "Qwen/Qwen2.5-72B-Instruct"
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


def system_prompt(host: str, guest: str, last_speaker: str | None) -> str:
    seed = (
        f"上一个 chunk 末尾说话人是 **{last_speaker}**,本 chunk 开头默认延续此说话人,直到从语境判断切换。"
        if last_speaker
        else f"第一个 chunk 通常以主持人 **{host}** 的开场白开始。"
    )
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
6. 标注独占一行,前后各空一行,例:

   **{host}**

   你之前提到......

   **{guest}**

   是的,我们的看法是......

7. 通过语境判断说话人切换:谁在提问、谁在回答、自我介绍、提及"我们公司是 X"、"今天的嘉宾"等线索
8. 一段话内不要切换说话人;不确定时延续当前说话人
9. {seed}

输出要求:
10. 直接输出译文,前后不要加说明文字、引号、标题
11. 第一行就是说话人标注或正文,不要前置任何说明"""


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


def fetch_transcript_en(video_id: str) -> str:
    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
    text = " ".join(snippet.text for snippet in fetched)
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
                    guest: str, last_speaker: str | None) -> str:
    resp = client.chat.completions.create(
        model=model,
        max_tokens=8192,
        temperature=0.3,
        messages=[
            {"role": "system", "content": system_prompt(host, guest, last_speaker)},
            {"role": "user", "content": chunk},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def translate_with_speakers(client: OpenAI, model: str, en_text: str,
                            host: str, guest: str) -> str:
    chunks = chunk_by_sentence(en_text, CHUNK_CHAR_LIMIT)
    print(f"      翻译 {len(chunks)} 块 (model={model}, host={host}, guest={guest})")
    parts: list[str] = []
    last_speaker: str | None = None
    for i, ch in enumerate(chunks, 1):
        print(f"      [{i}/{len(chunks)}] {len(ch):,} 字符 → 翻译中…")
        zh = translate_chunk(client, model, ch, host, guest, last_speaker)
        parts.append(zh)
        last_speaker = detect_last_speaker(zh, host, guest) or last_speaker
    return "\n\n".join(parts)


def build_frontmatter(*, title: str | None, guest: str | None,
                      guest_company: str | None, date: str | None,
                      video_id: str, url: str) -> str:
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
    lines.append("source: youtube-auto-captions")
    lines.append("status: working-draft  # 工作稿,未经说话人审阅")
    lines.append("---")
    return "\n".join(lines)


def write_episode(out_path: Path, frontmatter: str, h1_title: str, body: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        f"{frontmatter}\n\n# {h1_title}\n\n{body.strip()}\n",
        encoding="utf-8",
    )


def run_url(client: OpenAI, model: str, url: str, out_dir: Path,
            filename_template: str, override_guest: str | None,
            override_title: str | None) -> None:
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

    print(f"[3/4] 翻译 + 说话人标注")
    body = translate_with_speakers(client, model, en, HOST_NAME, guest)

    print(f"[4/4] 写入")
    fname = format_filename(
        filename_template,
        date=upload_date,
        title=title,
        guest=guest,
        guest_company=meta.get("author_name"),
        video_id=vid,
    )
    out_path = out_dir / f"{fname}.md"
    fm = build_frontmatter(
        title=title,
        guest=guest,
        guest_company=meta.get("author_name"),
        date=upload_date,
        video_id=vid,
        url=url,
    )
    h1 = f"{guest} — {title}" if title and title != vid else (title or vid)
    write_episode(out_path, fm, h1, body)
    print(f"      ✓ {out_path}")


def split_frontmatter(md_text: str) -> tuple[str, str]:
    if md_text.startswith("---\n"):
        end = md_text.find("\n---\n", 4)
        if end != -1:
            return md_text[: end + 5], md_text[end + 5 :]
    return "", md_text


def run_file(client: OpenAI, model: str, path: Path, out_dir: Path,
             filename_template: str, override_guest: str | None,
             override_title: str | None) -> None:
    print(f"[1/3] 读文件: {path}")
    raw = path.read_text(encoding="utf-8")
    fm_in, body_in = split_frontmatter(raw)
    print(f"      正文 {len(body_in):,} 字符 (frontmatter {'有' if fm_in else '无'})")

    title = override_title or path.stem
    guest = override_guest or "Guest"

    print(f"[2/3] 翻译 + 说话人标注")
    body = translate_with_speakers(client, model, body_in.strip(), HOST_NAME, guest)

    print(f"[3/3] 写入")
    out_name = override_title or path.stem
    fname = format_filename(
        filename_template,
        date=_date.today().isoformat(),
        title=out_name,
        guest=guest,
        guest_company=None,
        video_id="local",
    )
    out_path = out_dir / f"{fname}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fm_in:
        out_path.write_text(f"{fm_in.rstrip()}\n\n{body.strip()}\n", encoding="utf-8")
    else:
        fm_new = build_frontmatter(
            title=title, guest=guest, guest_company=None,
            date=None, video_id="local", url=str(path),
        )
        write_episode(out_path, fm_new, title, body)
    print(f"      ✓ {out_path}")


def main() -> int:
    p = argparse.ArgumentParser(description="英文播客 transcript → 中文(带说话人)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="YouTube 视频 URL")
    src.add_argument("--file", help="本地英文 md 文件路径")
    p.add_argument("--out", default="./transcripts", help="输出目录(默认 ./transcripts)")
    p.add_argument("--guest", default=None, help="覆盖嘉宾名(标题抽不准时手动指定)")
    p.add_argument("--title", default=None, help="覆盖标题")
    p.add_argument("--model", default=MODEL, help=f"模型 ID(默认 {MODEL})")
    p.add_argument(
        "--filename-template",
        default="{date}_{title}",
        help="文件名模板,占位符:{date} {title} {guest} {guest_company} {video_id}",
    )
    args = p.parse_args()

    api_key = os.environ.get("SILICONFLOW_API_KEY")
    if not api_key:
        print("错误:请先 export SILICONFLOW_API_KEY=...", file=sys.stderr)
        return 1

    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    out_dir = Path(args.out)

    if args.url:
        run_url(client, args.model, args.url, out_dir, args.filename_template,
                args.guest, args.title)
    else:
        run_file(client, args.model, Path(args.file), out_dir,
                 args.filename_template, args.guest, args.title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
