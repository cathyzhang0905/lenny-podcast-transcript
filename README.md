# Lenny's Podcast → 中文 Transcript 自动化

把 Lenny's Podcast(或任意 YouTube 频道)的英文播客自动翻译成**带说话人标注的中文逐字稿**,支持周期监听新集 + Obsidian 友好的 YAML frontmatter。

📂 **看产物**:[`transcripts/`](transcripts/) 目录(自动生成,定期更新)

> ⚠️ 译文为工作稿,未经说话人审阅。基于 YouTube 自动字幕翻译,质量受其 ASR 上限制约。

## 特性

- ✅ **完整逐字翻译**(非摘要)+ **说话人标注**(`**Lenny**` / `**<Guest>**` 块式)
- ✅ **YAML frontmatter**(title / guest / date / video_id),Obsidian Dataview 友好
- ✅ **Provider 无关**:任何 OpenAI 兼容协议(OpenAI / DeepSeek / 硅基流动 / Moonshot / 智谱 / OpenRouter / Ollama 本地 ...)
- ✅ **RSS 监听 + 自动去重**:扫已翻译文件的 frontmatter,只翻新集
- ✅ **多频道扩展** + 可配置文件名模板

❌ 不做摘要 / 不做 audio download / 不做 Whisper diarization

## 输出长这样

```markdown
---
title: "How Anthropic's product team moves faster | Cat Wu"
guest: "Cat Wu"
guest_company: "Lenny's Podcast"
date: 2026-04-23
video_id: PplmzlgE0kg
url: https://www.youtube.com/watch?v=PplmzlgE0kg
source: youtube-auto-captions
status: working-draft  # 工作稿,未经说话人审阅
---

# Cat Wu — How Anthropic's product team moves faster

**Lenny**

我从没见过哪家公司能像你们 Anthropic 这样快地出货。你面试过上百位 PM,
一直觉得很多人切入这件事的方式是不对的——展开讲讲?

**Cat Wu**

我们就是想把所有阻碍出货的障碍一个个拆掉。很多产品功能的交付周期,
已经从六个月缩短到一个月,有时候甚至一天就能上。PM 这个角色正在
发生非常大的变化,核心是迭代要足够快。

**Lenny**

那你觉得未来 PM 需要培养的能力是什么?

**Cat Wu**

归根结底还是产品品味。当写代码变得越来越廉价,真正值钱的就是
判断该写什么。
```

## 快速开始

### 1. 装环境

```bash
git clone https://github.com/cathyzhang0905/lenny-podcast-transcript.git
cd lenny-podcast-transcript
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配 LLM provider

```bash
cp config.example.yaml config.yaml   # config.yaml 已 gitignore,不会污染你的 fork
```

打开 `config.yaml`,顶部注释列了 11 个常见 provider 的 `ai_base_url` + `ai_model` 速查表(OpenAI / DeepSeek / 硅基流动 / Moonshot / 智谱 / 通义 / OpenRouter / Ollama 等)。改 2 行就能切。

API key 走 env var:

```bash
export AI_API_KEY="sk-..."
```

### 3. 跑一集试试

```bash
python lenny_transcript.py --url "https://www.youtube.com/watch?v=PplmzlgE0kg"
# 输出:transcripts/2026-04-23_How-Anthropics-product-team-moves-faster.md
```

### 4. 监听新集(自动去重)

```bash
python watcher.py --dry-run     # 看 RSS 里有哪些新集
python watcher.py --limit 1     # 跑最新 1 集试水
python watcher.py               # 跑所有未翻译的新集
```

### 5. 周期化(可选)

**macOS / launchd**:

```bash
cp scripts/com.lenny-transcript.weekly.plist.example \
   ~/Library/LaunchAgents/com.lenny-transcript.weekly.plist
# 编辑 <REPO_PATH> 和 <YOUR_API_KEY>
launchctl load ~/Library/LaunchAgents/com.lenny-transcript.weekly.plist
```

**Linux / cron**:

```bash
crontab -e
# 每周一 09:00:
0 9 * * 1 cd /path/to/repo && source .venv/bin/activate && AI_API_KEY=sk-... python watcher.py >> run.log 2>&1
```

## FAQ

**Q: 我跑了出 `RequestBlocked` 怎么办?**

YouTube 短期 rate-limit 你的 IP(常见于反复跑同一个视频)。等 30-60 分钟换网络再试。如果跑在云厂商 IP(GitHub Actions / AWS / GCP),大概率会被永久封 —— 需要旋转代理或换本地跑。

**Q: 说话人标错了怎么修?**

LLM 从语境推断,精度 ~85%。Obsidian 里手改即可。如果是嘉宾名抽错(看 frontmatter 的 `guest:` 字段),用 `python lenny_transcript.py --url ... --guest "Correct Name"` 显式覆盖。

**Q: 怎么找一个频道的 `channel_id`?**

浏览器打开该频道任意一集 → 右键查看页面源码 → 搜 `"channelId"` → 复制 `UC...` 那串。

**Q: 翻译质量不满意能换模型吗?**

能。改 `config.yaml` 的 `ai_model`(参考 `config.example.yaml` 顶部 11 厂商列表)。或单次跑用 `--model "..."` 覆盖。中文翻译的常见选择:Qwen2.5-72B(口语自然)/ DeepSeek-V3(术语稳)/ GPT-4o(通用强)。

**Q: 我能监听别的播客频道吗?**

能。`config.yaml` 的 `channels:` 加一项,改 `channel_id` 和 `host`。注意嘉宾名抽取启发式是按 Lenny 标题格式调的,其他频道可能要在 `extract_guest()` 加规则,或所有 episode 用 `--guest` 显式指定。

**Q: ASR 翻出错词(比如 Anthropic → Enthropic)怎么修?**

`lenny_transcript.py` 顶部有个 `ASR_FIXES` 字典在英文层硬替换。遇到新错词加一行,以后所有视频都生效。

**Q: `--filename-template` 在两边都有,哪个生效?**

`lenny_transcript.py` 单 URL 跑用命令行 `--filename-template`(默认 `{date}_{title}`);`watcher.py` 走 `config.yaml` 里的 `filename_template`。

## License

[MIT](LICENSE)。注意:`transcripts/` 下的中文译稿是基于第三方播客的派生工作稿,版权归原说话人所有,本仓库不主张其权利,仅作为个人学习/研究笔记保存。
