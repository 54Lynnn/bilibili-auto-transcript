# 📼 Bilibili Auto Transcript

**B站视频自动转录 & 收藏夹扫描技能**

三级降级策略：CC字幕 → B站AI字幕 → OpenAI Whisper 语音转文字，自动获取 B站视频的文字内容。

## 功能

- **三级字幕降级**：人工CC字幕 → AI字幕(9种语言) → Whisper 本地转录，逐级自动降级
- **智能模型选择**：有GPU且显存≥6GB用medium，<6GB用small；无GPU用base/tiny（依视频时长）
- **收藏夹扫描**：分页获取收藏夹所有视频，去重、断点续传
- **批量转录**：自动遍历收藏夹新视频，支持重试、报告生成
- **AI摘要**（可选）：设置 `OPENAI_API_KEY` 后自动生成结构化视频摘要
- **目录组织**：按视频发布年月自动分目录存储

## 设计决策

v5.0 从 Qwen3-ASR 换回了 Whisper 作为本地语音转文字引擎。原因：

- **架构差异** — Qwen3-ASR 是 **LLM 做语音转文字**，音频整段送进大语言模型推理，慢且吃显存。Whisper 是**纯语音识别模型**，30 秒一段做声学特征识别，不需要 LLM 推理，快得多
- **资源占用** — Qwen3-ASR-1.7B 需要 4-6GB 显存且推理时间久，Whisper 有更轻量的模型可选（tiny 仅 39MB）
- **安装省心** — `pip install openai-whisper` 一行搞定，模型自动下载。Qwen3-ASR 需从 HuggingFace 下 2-5GB 权重
- **够用即可** — 语音转文字是三级降级的最后兜底，为这个场景扛一个 LLM 级别的模型不值当

## 快速开始

```bash
# 1. 安装依赖（首次）
cd ~/.openclaw/workspace/skills/bilibili-auto-transcript
python3 -m venv .venv
.venv/bin/pip install openai-whisper requests python-dotenv

# 2. 手动转录单个视频
bash scripts/bilibili_transcript.sh "https://www.bilibili.com/video/BVxxxxx/"

# 3. 批量转录收藏夹所有新视频
.venv/bin/python3 scripts/batch_transcribe.py
```

## 依赖

- yt-dlp — 视频/字幕下载
- ffmpeg — 音频处理
- `openai-whisper` — 本地语音转文字引擎（通过 `.venv/bin/pip install openai-whisper` 安装）
- `requests` — HTTP 请求（批量转录用）
- `python-dotenv` — 加载 `.env` 文件（通过 `.venv/bin/pip install python-dotenv` 安装）
- opencc — 繁转简（可选）
- chromium-browser — Cookie支持（B站AI字幕）

## 配置

1. `cp .env.example .env`，编辑 `.env` 设置 `FAV_MEDIA_ID`（收藏夹ID）和 `OPENAI_API_KEY`（AI摘要）
2. 用 chromium-browser 登录 bilibili.com 获取 Cookie
3. 支持任何 OpenAI 兼容 API（DeepSeek、OpenCode Go、OpenRouter 等）

## 项目结构

```
bilibili-auto-transcript/
├── SKILL.md                    # Skill 元数据
├── .env                        # API密钥（不提交git）
├── .env.example                # 配置模板（提交git，供朋友参考）
├── .db/                        # SQLite 数据库（不提交git）
│   └── transcripts.db          # 转录记录+摘要数据库
├── scripts/
│   ├── bilibili_scanner.py     # 收藏夹扫描
│   ├── bilibili_transcript.sh  # 核心转录引擎（v5.0，Whisper）
│   ├── generate_summary.py     # AI摘要生成器（三种模式统一调用）
│   ├── transcript_db.py        # SQLite 数据库管理层
│   ├── fill_summaries.py       # 批量补摘要（cronjob推荐）
│   ├── migrate_to_db.py        # 旧TXT迁移到数据库
│   ├── logger.py               # 共享日志模块
│   └── batch_transcribe.py     # 批量转录调度
└── references/
    ├── architecture.md         # 架构说明
    └── bilibili-fav-api.md     # B站API参考
```

## 许可

MIT
