#!/usr/bin/env python3
"""周期性检查配置的 YouTube 频道是否有新集,把新集翻译成中文 transcript。

工作流:
  1. 读 config.yaml,遍历 channels
  2. 对每个频道拉 YouTube RSS feed(免费,不需 API key)
  3. 扫 transcripts/ 里已翻译过的 video_id(从 YAML frontmatter)
  4. 新集才调翻译;已存在的跳过
  5. 输出到 config 指定的 output_dir
"""

import argparse
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from openai import OpenAI

from lenny_transcript import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    HOST_NAME,
    _output_path,
    _resolve_langs,
    build_frontmatter,
    extract_guest,
    fetch_transcript_en,
    fetch_video_meta,
    format_filename,
    process_with_speakers,
    write_episode,
)

RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}


def fetch_channel_feed(channel_id: str) -> list[dict]:
    url = RSS_URL.format(channel_id=channel_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        xml_text = r.read()
    root = ET.fromstring(xml_text)
    items: list[dict] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        vid_elem = entry.find("yt:videoId", ATOM_NS)
        title_elem = entry.find("atom:title", ATOM_NS)
        link_elem = entry.find("atom:link", ATOM_NS)
        pub_elem = entry.find("atom:published", ATOM_NS)
        if vid_elem is None or vid_elem.text is None:
            continue
        items.append({
            "video_id": vid_elem.text,
            "title": (title_elem.text if title_elem is not None else "") or "",
            "url": link_elem.attrib.get("href", "") if link_elem is not None else "",
            "published": (pub_elem.text or "")[:10] if pub_elem is not None else "",
        })
    return items


def known_video_ids(transcripts_dir: Path) -> set[str]:
    ids: set[str] = set()
    if not transcripts_dir.exists():
        return ids
    for fp in transcripts_dir.glob("*.md"):
        try:
            head = fp.read_text(encoding="utf-8", errors="ignore")[:1500]
            m = re.search(r"^video_id:\s*(\S+)\s*$", head, flags=re.MULTILINE)
            if m:
                ids.add(m.group(1).strip())
        except Exception:
            pass
    return ids


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> int:
    p = argparse.ArgumentParser(description="Watch YouTube channels and translate new episodes.")
    p.add_argument("--config", default="./config.yaml", help="config 路径(默认 ./config.yaml)")
    p.add_argument("--dry-run", action="store_true", help="只列出待翻译的新视频,不调 LLM")
    p.add_argument("--limit", type=int, default=None, help="本次最多翻译多少集(避免首次跑爆)")
    args = p.parse_args()

    api_key = os.environ.get("AI_API_KEY")
    if not api_key and not args.dry_run:
        print("错误:请先 export AI_API_KEY=...", file=sys.stderr)
        return 1

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"错误:config 不存在 {cfg_path}", file=sys.stderr)
        print("       先 cp config.example.yaml config.yaml,然后按需修改", file=sys.stderr)
        return 1
    cfg = load_config(cfg_path)
    transcripts_dir = Path(cfg.get("output_dir", "./transcripts"))
    template = cfg.get("filename_template", "{date}_{title}")
    model = cfg.get("ai_model", DEFAULT_MODEL)
    base_url = cfg.get("ai_base_url", DEFAULT_BASE_URL)
    output_lang = cfg.get("output_lang", "zh")
    langs = _resolve_langs(output_lang)
    multi = len(langs) > 1
    channels = cfg.get("channels", [])
    if not channels:
        print("config 里没有配置 channels", file=sys.stderr)
        return 1

    client = None if args.dry_run else OpenAI(api_key=api_key, base_url=base_url)
    seen = known_video_ids(transcripts_dir)
    print(f"已翻译 {len(seen)} 集,扫描自 {transcripts_dir}/")

    total_new = 0
    for ch in channels:
        ch_name = ch.get("name", "?")
        ch_id = ch.get("channel_id")
        host = ch.get("host", HOST_NAME)
        if not ch_id:
            print(f"  ⚠️ {ch_name} 缺 channel_id,跳过")
            continue
        print(f"\n=== Channel: {ch_name} ({ch_id}) ===")
        try:
            feed = fetch_channel_feed(ch_id)
        except Exception as e:
            print(f"  ✗ 拉 RSS 失败: {e}")
            continue
        new_items = [it for it in feed if it["video_id"] not in seen]
        print(f"  RSS 返回 {len(feed)} 集,其中新集 {len(new_items)}")
        if args.limit is not None:
            new_items = new_items[: args.limit]
            print(f"  应用 --limit {args.limit},本次实际处理 {len(new_items)} 集")

        for item in new_items:
            print(f"\n  → {item['video_id']} | {item['title']!r}")
            if args.dry_run:
                continue
            try:
                meta = fetch_video_meta(item["video_id"])
                title = meta.get("title") or item["title"]
                guest = extract_guest(title, host=host) or "Guest"
                upload_date = meta.get("upload_date") or item["published"][:10]
                print(f"      title={title!r}")
                print(f"      guest={guest!r}  date={upload_date}")
                en = fetch_transcript_en(item["video_id"])
                print(f"      英文 {len(en):,} 字符")
                fname = format_filename(
                    template, date=upload_date, title=title, guest=guest,
                    guest_company=meta.get("author_name"), video_id=item["video_id"],
                )
                h1 = f"{guest} — {title}" if title else item["video_id"]
                for li, lg in enumerate(langs, 1):
                    print(f"      ({li}/{len(langs)}) lang={lg}")
                    body = process_with_speakers(client, model, en, host, guest, lg)
                    fm = build_frontmatter(
                        title=title, guest=guest,
                        guest_company=meta.get("author_name"), date=upload_date,
                        video_id=item["video_id"], url=item["url"], lang=lg,
                    )
                    out_path = _output_path(transcripts_dir, fname, lg, multi)
                    write_episode(out_path, fm, h1, body)
                    print(f"      ✓ {out_path}")
                seen.add(item["video_id"])
                total_new += 1
            except Exception as e:
                print(f"      ✗ 失败: {e}")

    print(f"\n=== 完成,本次翻译 {total_new} 集 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
