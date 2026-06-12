---
name: bilibili-auto-transcript
version: "5.2.0"
description: "B站视频转录+收藏夹扫描。三级降级（CC→AI→Whisper），AI摘要生成。"
homepage: https://clawhub.ai/54lynnn/bilibili-transcript
metadata:
  {
    "openclaw":
      {
        "emoji": "📼",
        "requires": { "bins": ["yt-dlp", "ffmpeg", "curl"] },
        "install":
          [
            {
              "id": "venv",
              "kind": "shell",
              "command": "cd {{SKILL_DIR}} && python3 -m venv .venv && .venv/bin/pip install openai-whisper requests python-dotenv",
              "label": "Setup virtual env & install Whisper",
            },
          ],
      },
  }
---

# 📼 Bilibili 视频转录 & 收藏夹自动扫描

**双模式技能** — 可以手动转录单个视频，也可以定时扫描收藏夹自动处理。

## 模式一：手动转录

当你给我一个 B站链接时，我会自动执行转录。

**用法：**
```bash
bash scripts/bilibili_transcript.sh "https://www.bilibili.com/video/BVxxxxx/"
```

**转录优先级（自动降级）：**
1. ✅ **人工CC字幕**（zh-CN, zh-TW, en, ja 等）→ 100%准确，秒出
2. ✅ **AI字幕**（ai-zh, ai-en, ai-ja 等9种语言）→ 85-90%准确，秒出
3. ✅ **OpenAI Whisper 语音转文字**（智能选模型）→ 有独显≥6GB 用 medium，<6GB 用 small；无独显用 base/tiny

**Whisper 智能模型选择：**

| 条件 | 模型 | 速度参考 |
|:----:|:----:|:--------:|
| **有 GPU，显存 ≥6GB** | medium | 高质量，~0.3x 实时 |
| **有 GPU，显存 <6GB** | small | 平衡，~0.5x 实时 |
| **无 GPU，视频 ≤30 分钟** | base | 质量与速度平衡 |
| **无 GPU，视频 >30 分钟** | tiny | 避免等待过久 |

- 自动检测 CUDA / nvidia-smi 获取显存
- 音频自动转为 16kHz 单声道 WAV（统一格式）

### 设计决策：为什么从 Qwen3-ASR 换回 Whisper？

v4.x 引入了 Qwen3-ASR 作为本地转录引擎，v5.0 换回了 Whisper。核心原因：

1. **架构差异巨大** — Qwen3-ASR 是 **LLM 做语音转文字**，把音频整段送进大语言模型做推理，1.7B 模型要完整加载 LLM 权重，显存占用大、推理慢。Whisper 是**纯语音识别模型**，音频切成 30 秒一段做声学特征识别，不需要 LLM 推理，速度快得多
2. **资源占用** — Qwen3-ASR-1.7B 需要 4-6GB 显存且推理时间长（LLM 的 O(n²) attention），Whisper medium 虽然也要 ~5GB 显存但处理方式轻量，且有更小的模型可选（tiny 仅 ~39MB）
3. **安装省心** — `pip install openai-whisper` 一行搞定，模型首次使用时自动下载。Qwen3-ASR 需从 HuggingFace 下载 2-5GB 权重，国内网络经常失败
4. **够用即可** — 语音转文字在这个 skill 里是**三级降级的最后一环**，大多数视频走 CC 或 AI 字幕就完了。为这个兜底场景扛一个 LLM 级别的模型，不值当

**⚠️ 关于摘要：** 设置了 `OPENAI_API_KEY` 时，转录完成后脚本会自动调用 `generate_summary.py` 生成 AI 摘要。未设置 API key 时 TXT 中保留占位符，可后续运行 `fill_summaries.py` 批量补全。

转录只负责出文件，索引那是 knowledge-rag 自己的事。

---

## 模式二：收藏夹自动扫描

定时检查 B站收藏夹，发现新视频后自动完成「转录 → AI 摘要 → 保存 → 通知」全流程。

### 工作流

```
定时触发 → 扫描收藏夹API → 对比已处理列表
  → 发现新视频 → 转录（三级降级）
  → （可选）AI读全文、写结构化摘要
  → 覆盖TXT中的摘要占位符
  → 记录bvid到已处理列表
  → 生成转录报告CSV
  → 通知用户（标题/作者/时长/转录来源/摘要/TXT文件）
```

### 批量转录（推荐）

```bash
.venv/bin/python3 scripts/batch_transcribe.py
```

自动扫描收藏夹全部视频，逐个转录，支持：
- **断点续传** — 中断后重跑自动跳过已处理视频
- **自动重试** — 失败任务自动重试2次
- **转录报告** — 生成 CSV 报告，含来源分布统计
- **AI摘要** — 有 API key 时自动生成（三种模式统一调用 `scripts/generate_summary.py`）
- **目录组织** — 按视频发布年月自动分目录存储
- **标题校验** — 转录完成后自动对比B站最新标题，UP主改标题时自动修正

### 首次设置

#### 1. 安装依赖
在技能目录下创建虚拟环境并安装依赖：
```bash
cd ~/.openclaw/workspace/skills/bilibili-auto-transcript
python3 -m venv .venv
.venv/bin/pip install openai-whisper requests python-dotenv
```

#### 2. 创建收藏夹
B站新建一个收藏夹，设为**公开**。

#### 3. 获取收藏夹ID
URL 中 `fid=` 后面的数字。

#### 4. 配置 AI 摘要（可选）
```bash
cd ~/.openclaw/workspace/skills/bilibili-auto-transcript
cp .env.example .env
# 编辑 .env，填入你的 API Key
```
支持任何 OpenAI 兼容 API（DeepSeek、OpenCode Go、OpenRouter 等），详见 `.env.example`。
编辑 `.env`，设置 `FAV_MEDIA_ID` 为你的收藏夹ID。

#### 5. Chromium 登录B站（获取Cookie）
```bash
chromium-browser &
# 打开 bilibili.com 并登录
```

#### 6. 检查依赖
```bash
yt-dlp --version    # 必需
ffmpeg -version     # 必需
.venv/bin/python3 -c "import whisper; print('Whisper OK')"  # 必需
opencc --version    # 可选，繁转简
```

#### 7. 配置定时任务（推荐每6小时扫描，有新内容则转录）
```bash
openclaw cron add \
  --name bilibili-auto-transcribe \
  --every 21600000 \
  --message "先用扫描脚本快速检查：cd ~/.openclaw/workspace/skills/bilibili-auto-transcript/scripts && .venv/bin/python3 bilibili_scanner.py。如果有新视频（NEW_ITEMS不为0），再用转录脚本：.venv/bin/python3 batch_transcribe.py。如果没新视频，直接说'无新内容'。如果有转完的视频，汇报成功/失败数量和标题。"
```

#### 8. 补全遗漏摘要（推荐每12小时）
```bash
openclaw cron add \
  --name bilibili-fill-summaries \
  --every 43200000 \
  --message "cd ~/.openclaw/workspace/skills/bilibili-auto-transcript && .venv/bin/python3 scripts/fill_summaries.py"
```
确保所有转录视频都有AI摘要。即使即时转录时API调用失败，也会被自动补上。

---

## 公共部分

### 转录脚本
`scripts/bilibili_transcript.sh` — 两个模式共享同一个引擎（v5.0）。转录完自动写入 SQLite 数据库。
`scripts/generate_summary.py` — AI摘要生成器，三种模式统一调用（转录完自动触发）。
`scripts/transcript_db.py` — SQLite 数据库管理层（建表、写入、查询、更新摘要）。
`scripts/fill_summaries.py` — 批量补摘要：扫描数据库中摘要为空的条目，逐个调API填充。适合 cronjob 定时运行。
`scripts/logger.py` — 共享日志模块，所有脚本关键操作写入 `~/.openclaw/workspace/.auto-transcript-state/logs/`。

### 依赖
- `yt-dlp` — 视频下载、字幕获取
- `ffmpeg` — 音频处理
- `openai-whisper` — 本地语音转文字引擎（通过 `.venv/bin/pip install openai-whisper` 安装）
- `requests` — HTTP 请求（批量转录用）
- `python-dotenv` — 加载 `.env` 文件（通过 `.venv/bin/pip install python-dotenv` 安装）
- `opencc` — 繁转简（可选）
- `chromium-browser` — Cookie 支持（B站AI字幕）

### 输出文件格式
```
================================================================================
B站视频转录文档
================================================================================

📹 视频标题：xxx
🔗 B站链接：xxx
👤 作者：xxx
📅 发布时间：xxx
⏱️  视频时长：xxx
📝 转录来源：CC字幕 / B站AI字幕 / Whisper medium（GPU加速）
⏰ 转录时间：xxx

================================================================================
第一部分：视频摘要（AI生成）
================================================================================

【AI待处理：请阅读全文后，替换此行，写结构化摘要】
（设置 OPENAI_API_KEY 后自动生成）

================================================================================
第二部分：完整原文
================================================================================

（完整转录内容...）

================================================================================
文档结束
================================================================================
```

### 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 收藏夹ID | （需设置） | URL `fid=` 的数字 |
| 输出目录 | `~/workspace/knowledge/bilibili/` | TXT存放路径，自动按年/月分子目录 |
| 已处理记录 | `~/.openclaw/workspace/.auto-transcript-state/processed_videos.txt` | 去重文件（每行一个bvid） |
| 转录数据库 | `bilibili-auto-transcript/.db/transcripts.db` | SQLite 数据库（bvid、标题、作者、转录来源、摘要等） |
| 转录报告 | `~/.openclaw/workspace/.auto-transcript-state/transcript_report.csv` | 每次批量转录的详细报告 |
| 扫描间隔 | 每6小时 | 自动模式定时 |
| OPENAI_API_KEY | （可选） | 设置后自动生成AI摘要，支持 `.env` 文件 |
| SUMMARY_API_URL | `https://api.openai.com/v1/chat/completions` | API地址，支持任何 OpenAI 兼容 API |
| SUMMARY_API_MODEL | `gpt-4o-mini` | 模型名，如 `deepseek-v4-flash`、`gpt-4o-mini` 等 |

### B站收藏夹API
```
GET https://api.bilibili.com/x/v3/fav/resource/list?media_id={ID}&ps=20&pn=1
```
- `ps` 最大20（脚本已设 ps=20）
- 公开收藏夹无需Cookie

### bvid
- `bvid` / `bv_id` = BV号 → 构建转录URL、去重追踪用
- `id` = avid（数字）→ 备用标识

### 注意事项
1. **同文件覆盖** — 同一BV号多次转录覆盖旧文件，已处理列表防重复
2. **需要Cookie** — 通过 Chromium cookie 获取 AI 字幕，需先B站登录；Cookie快过期时脚本会提示
3. **Whisper 首次运行** — 首次使用时自动下载模型权重（tiny ~39MB / base ~74MB / small ~244MB / medium ~769MB），后续使用无需下载
4. **Whisper 耗时** — GPU模式约实时 0.3x-0.5x 倍速，CPU模式约实时 0.5x-2x 倍速（依模型大小）
5. **虚拟环境** — 所有 Python 脚本需在 `.venv` 中运行：`.venv/bin/python3 scripts/xxx.py`；`bilibili_transcript.sh` 会自动检测并提示安装
6. **B站API ps上限20** — 超过需分页
7. **AI摘要自动生成** — 设置 `OPENAI_API_KEY`（或 `.env` 文件），转录完成后自动生成结构化摘要；未设置则保留占位符待 Agent 手动处理
8. **只干自己的事** — 转录只输出文件。索引是 knowledge-rag 的事情
9. **输出目录** — 自 v3.0 起按视频发布年月自动组织目录（如 `bilibili/2026/06/`）

## 推荐搭配：📖 Knowledge RAG

装了这个 skill 后再装 **knowledge-rag**，知识库会定时自动扫描新文件并索引，无需手动操作：

```bash
clawhub install knowledge-rag
```

转录后自动索引，随时用自然语言搜索所有转过的内容，还有网页搜索界面。

---

## 📦 开源 & 交流

- **GitHub**：[github.com/54Lynnn/bilibili-auto-transcript](https://github.com/54Lynnn/bilibili-auto-transcript)（⭐️ Star 支持）
- **ClawHub**：[clawhub.ai/54lynnn/bilibili-auto-transcript](https://clawhub.ai/54lynnn/bilibili-auto-transcript)
- **QQ 群**：120363664（欢迎扫码加入交流）
