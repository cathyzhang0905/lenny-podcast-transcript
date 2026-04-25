# Lenny's Podcast → 中文 Transcript 自动化

把 Lenny's Podcast(或任意 YouTube 频道)的英文播客自动翻译成**带说话人标注的中文逐字稿**,支持周期监听新集 + Obsidian 友好的 YAML frontmatter。

> ⚠️ 译文为工作稿,未经说话人审阅。使用 YouTube 自动字幕作为输入,翻译质量受其 ASR 上限限制。

## 是什么 / 不是什么

- ✅ **完整逐字翻译**(非摘要),保留对话所有细节
- ✅ **说话人标注**(`**Lenny**` / `**<Guest>**` 块式 markdown,Obsidian 双链友好)
- ✅ **重要术语保留英文**(`Claude Code` / `Anthropic` / `RAG` / `PMF` 等)
- ✅ **YAML frontmatter**(title / guest / date / video_id / url),Dataview / 双链友好
- ✅ **自动去重**:扫已翻译文件的 frontmatter,RSS 拉到的视频如果翻过了就跳
- ✅ **多频道扩展**:`config.yaml` 加一行就能监听 No Priors / Latent Space 等
- ✅ **可配置文件名模板**:`{date}_{title}` / `{guest}_{video_id}` / 你想怎么命名都行
- ❌ 不是法律授权的官方翻译,只是个人消化工具
- ❌ 不替代英文原文(精确引用、口音、停顿等都丢了)
- ❌ 不做摘要 / 不做 audio download / 不做 Whisper diarization

## 架构

```
config.yaml (你写的频道列表 + 命名规则 + 模型)
    ↓
watcher.py
    ├─ 拉每个频道的 YouTube RSS feed (免费,无需 API key)
    ├─ 比对 transcripts/ 里已有 video_id (从 YAML frontmatter 扫出)
    └─ 新集 → 调 lenny_transcript.py
              ├─ oembed 拿 title + author
              ├─ 启发式从标题抽 guest 名
              ├─ youtube-transcript-api 拉英文字幕
              ├─ ASR 纠错字典(Vercel/Replit/Claude Code 等高频词修正)
              ├─ 切块 → Sonnet/Qwen 边翻边贴说话人标签 (chunk 间用上一段末尾说话人做 seed)
              └─ 输出:YAML frontmatter + 中文 markdown → transcripts/<template>.md
```

## 快速开始

### 1. 拿一个 OpenAI 兼容 API key

推荐 [硅基流动](https://cloud.siliconflow.cn/)(国内充值方便,Qwen2.5-72B 翻译效果对中文最自然)。也支持任意 OpenAI 兼容协议(DeepSeek / OpenAI / Moonshot / OpenRouter):改 `config.yaml` 的 `model` 和 `lenny_transcript.py` 顶部的 `BASE_URL`。

### 2. 装环境

```bash
git clone <this-repo>
cd lenny-podcast-transcript
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 配 key + 跑一集

```bash
export SILICONFLOW_API_KEY="sk-..."
python lenny_transcript.py --url "https://www.youtube.com/watch?v=PplmzlgE0kg"
# 输出:transcripts/2026-04-23_How-Anthropics-product-team-moves-faster.md
```

### 4. 配多频道 / 自动监听

```bash
cp config.example.yaml config.yaml   # 已默认 Lenny,直接用就行
python watcher.py --dry-run          # 看 RSS 里有哪些新集
python watcher.py --limit 1          # 跑最新 1 集试水
python watcher.py                    # 跑所有未翻译的新集
```

### 5. 让它每周自动跑(macOS launchd)

```bash
# 把模板复制到 LaunchAgents 目录,改两个占位符再 load
cp scripts/com.lenny-transcript.weekly.plist.example \
   ~/Library/LaunchAgents/com.lenny-transcript.weekly.plist
# 编辑里面的 <REPO_PATH> 和 <YOUR_API_KEY>
launchctl load ~/Library/LaunchAgents/com.lenny-transcript.weekly.plist
```

每周一 09:00 自动跑。日志看 `run.log`。

## 为什么不用 GitHub Actions

理论上 `.github/workflows/watch.yml` cron 是开源项目最自然的实现。**实际 YouTube 对云厂商 IP 段(GitHub / AWS / GCP / Azure)有大面积封禁**,`youtube-transcript-api` 在 GH Actions runner 上大概率从第一天就跑不通(`RequestBlocked` 错误)。

可行的解法:
- 加付费旋转代理(如 [Webshare](https://www.webshare.io/) ~$1-5/月)+ 在 workflow 里设 `HTTP_PROXY`
- 改用 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 替代 `youtube-transcript-api`(走另一条路径,有时能绕过)
- 跑在自己机器上(launchd / cron / systemd)

本仓库**默认走本地 launchd**,因为周更频道 + 个人电脑常开是合理假设;省钱省 IP 风险。

## 已知限制

- **ASR 错误传染**:YouTube 自动字幕里的拼错(Anthropic→Enthropic / Vercel→Verscell / Cat Wu→Cat Woo)会被翻译模型忠实搬运。已建立 `ASR_FIXES` 字典在英文层硬替换;遇到新错词加一行即可,见 `lenny_transcript.py:31`
- **说话人标注精度 ~85%**:LLM 从语境推断,偶尔会把"主持人讲嘉宾观点"标成嘉宾。Obsidian 里手改即可
- **嘉宾名抽取启发式**:Lenny 标题格式相对规整能 hit ~95%,其他频道可能要在 `extract_guest()` 加规则,或命令行 `--guest "Correct Name"` 覆盖
- **首次跑 RSS 会有 15 集积压**:YouTube RSS 默认返回最近 15 集,`watcher.py` 会全部翻一遍。建议首次跑用 `--limit 1` 试水

## 文件名模板

`config.yaml` 里 `filename_template` 默认 `{date}_{title}`,可换成:

| 模板 | 例子 |
|---|---|
| `{date}_{title}` (默认) | `2026-04-23_How-Anthropics-product-team-moves-faster.md` |
| `{title}` | `How-Anthropics-product-team-moves-faster.md` |
| `{date}_{guest}` | `2026-04-23_Cat-Wu.md` |
| `{guest}_{video_id}` | `Cat-Wu_PplmzlgE0kg.md` |
| `{video_id}` | `PplmzlgE0kg.md` |

## Claude Code 用户

附带一个轻量 skill,Claude Code 用户可以软链:

```bash
mkdir -p ~/.claude/skills
ln -s "$(pwd)/claude/skills/lenny-podcast-zh" ~/.claude/skills/
```

之后在 Claude Code 里贴 YouTube URL + 说"翻成中文",Claude 会自动调本工具。

## License

[MIT](LICENSE)
