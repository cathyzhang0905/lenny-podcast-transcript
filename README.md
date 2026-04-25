# Lenny's Podcast → 中文 Transcript 自动化

把 Lenny's Podcast(或任意 YouTube 频道)的英文播客自动翻译成**带说话人标注的中文逐字稿**,支持周期监听新集 + Obsidian 友好的 YAML frontmatter。

> ⚠️ 译文为工作稿,未经说话人审阅。使用 YouTube 自动字幕作为输入,翻译质量受其 ASR 上限限制。

## 是什么 / 不是什么

- ✅ **完整逐字翻译**(非摘要),保留对话所有细节
- ✅ **说话人标注**(`**Lenny**` / `**<Guest>**` 块式 markdown,Obsidian 双链友好)
- ✅ **重要术语保留英文**(`Claude Code` / `Anthropic` / `RAG` / `PMF` 等)
- ✅ **YAML frontmatter**(title / guest / date / video_id / url),Dataview 友好
- ✅ **自动去重**:扫已翻译文件的 frontmatter,RSS 拉到的视频翻过就跳
- ✅ **多频道扩展**:`config.yaml` 加一行就能监听 Latent Space / No Priors 等其他频道
- ✅ **Provider 无关**:任何 OpenAI 兼容协议都能跑(OpenAI / DeepSeek / 硅基流动 / Moonshot / 智谱 / OpenRouter / Ollama 本地 ...)
- ✅ **可配置文件名模板**:`{date}_{title}` / `{guest}_{video_id}` / 自定义
- ❌ 不是法律授权的官方翻译,只是个人消化工具
- ❌ 不替代英文原文(精确引用、口音、停顿等都丢了)
- ❌ 不做摘要 / 不做 audio download / 不做 Whisper diarization

## 快速开始

### 1. 装环境

```bash
git clone https://github.com/cathyzhang0905/lenny-podcast-transcript.git
cd lenny-podcast-transcript
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配 LLM provider + key

复制 example 配置,改成你想用的 provider:

```bash
cp config.example.yaml config.yaml
```

打开 `config.yaml` 看顶部的 provider 速查表 —— OpenAI / DeepSeek / 硅基流动 / Moonshot / 智谱 / 通义 / OpenRouter / Ollama 全部 OpenAI 兼容协议都能跑,改 `ai_base_url` + `ai_model` 两行即可。

API key 走 env var:

```bash
export AI_API_KEY="sk-..."   # 你选的 provider 给的 key
```

### 3. 跑一集试试

```bash
python lenny_transcript.py --url "https://www.youtube.com/watch?v=PplmzlgE0kg"
# 输出:transcripts/2026-04-23_How-Anthropics-product-team-moves-faster.md
```

打开生成的 md 看翻译质量,不满意可以 `--model` 换其他 model。

### 4. 监听新集

`config.yaml` 默认监听 Lenny's Podcast。加自己的频道在 `channels:` 列表里。

```bash
python watcher.py --dry-run          # 看 RSS 里有哪些新集
python watcher.py --limit 1          # 跑最新 1 集试水
python watcher.py                    # 跑所有未翻译的新集
```

`watcher.py` 自动扫 `transcripts/` 里已有的 `video_id`(从 YAML frontmatter),只翻没翻过的。

### 5. 周期化

#### macOS (launchd)

```bash
cp scripts/com.lenny-transcript.weekly.plist.example \
   ~/Library/LaunchAgents/com.lenny-transcript.weekly.plist
# 编辑文件,填 <REPO_PATH> 和 <YOUR_API_KEY>
launchctl load ~/Library/LaunchAgents/com.lenny-transcript.weekly.plist
```

每周一 09:00 自动跑。日志看 `run.log`。

#### Linux (cron)

```bash
crontab -e
# 加入:
0 9 * * 1 cd /path/to/repo && source .venv/bin/activate && AI_API_KEY=sk-... python watcher.py >> run.log 2>&1
```

## 文件名模板

`config.yaml` 里 `filename_template` 默认 `{date}_{title}`,可换成:

| 模板 | 例子 |
|---|---|
| `{date}_{title}` (默认) | `2026-04-23_How-Anthropics-product-team-moves-faster.md` |
| `{title}` | `How-Anthropics-product-team-moves-faster.md` |
| `{date}_{guest}` | `2026-04-23_Cat-Wu.md` |
| `{guest}_{video_id}` | `Cat-Wu_PplmzlgE0kg.md` |
| `{video_id}` | `PplmzlgE0kg.md` |

## 已知限制

- **ASR 错误传染**:YouTube 自动字幕里的拼错(`Anthropic` → `Enthropic` / `Vercel` → `Verscell`)会被翻译模型忠实搬运。已建立 `ASR_FIXES` 字典在英文层硬替换;遇到新错词加一行即可,见 `lenny_transcript.py`
- **说话人标注精度 ~85%**:LLM 从语境推断,偶尔会标错。Obsidian 里手改即可
- **嘉宾名抽取启发式**:Lenny 标题格式相对规整能命中 ~95%,其他频道可能要在 `extract_guest()` 加规则,或命令行 `--guest "Correct Name"` 覆盖
- **YouTube IP 限制**:短时间高频请求同一视频会触发 `RequestBlocked`;跑在云厂商 IP(GitHub Actions / AWS / GCP)大概率从一开始就被 ban。本仓库默认走本地 launchd / cron,跑在你自己机器上;如需云端跑,自行加旋转代理

## Claude Code 用户

附带一个轻量 skill,可以软链:

```bash
mkdir -p ~/.claude/skills
ln -s "$(pwd)/claude/skills/lenny-podcast-zh" ~/.claude/skills/
```

之后在 Claude Code 里贴 YouTube URL + 说"翻成中文",Claude 会自动调本工具。

## License

[MIT](LICENSE)
