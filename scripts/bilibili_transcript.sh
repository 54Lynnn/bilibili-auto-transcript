#!/bin/bash
# B站视频字幕智能获取脚本 v5.1
# 功能：CC字幕 → AI字幕 → Whisper 转录（三级降级）
# 支持：WSL Chromium/Edge Cookie、多语言AI字幕、GPU加速、音频优化
# v5.1 修复：Cookie检测逻辑（检查前5行输出避免版本警告干扰）

VIDEO_URL="$1"
OUTPUT_DIR="${2:-$HOME/workspace/knowledge/bilibili}"
mkdir -p "$OUTPUT_DIR"
BROWSER_TYPE="${3:-chromium}"

CLEANUP_DIR="$OUTPUT_DIR"
LOG_DIR="$HOME/.openclaw/workspace/.auto-transcript-state/logs"
LOG_FILE="$LOG_DIR/transcript.log"
mkdir -p "$LOG_DIR"

shell_log() {
    local level="${1:-INFO}"
    local message="$2"
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] [$level] [bilibili_transcript.sh] $message" >> "$LOG_FILE"
}

cleanup_temp() {
    rm -f "$CLEANUP_DIR"/bilibili_subtitle*.srt "$CLEANUP_DIR"/bilibili_ai_subtitle*.srt \
          "$CLEANUP_DIR"/bilibili_audio*.mp3 "$CLEANUP_DIR"/bilibili_audio*.m4a \
          "$CLEANUP_DIR"/bilibili_audio*.wav "$CLEANUP_DIR"/bilibili_audio*.txt \
          "$CLEANUP_DIR"/.qwen_transcript.txt
}
trap cleanup_temp EXIT

if [ -z "$VIDEO_URL" ]; then
    echo "用法: $0 <B站视频链接> [输出目录] [浏览器类型:chromium|edge|firefox]"
    exit 1
fi

echo "🔍 正在获取视频信息..."

# ===== 检测浏览器Cookie =====
echo "🔍 检测浏览器Cookie..."

COOKIE_ARGS=()
DETECTED_COOKIE_PATH=""

detect_cookie() {
    local browser="$1"
    local path="$2"
    local label="$3"
    if [ -d "$path" ]; then
        local test_out
        test_out=$(yt-dlp --list-subs --cookies-from-browser "$browser:$path" "$VIDEO_URL" 2>&1 | head -5)
        if echo "$test_out" | grep -q "Extracting"; then
            echo "   ✅ 使用 $label Cookie"
            COOKIE_ARGS=(--cookies-from-browser "$browser:$path")
            DETECTED_COOKIE_PATH="$path/Default/Cookies"
            return 0
        fi
    fi
    return 1
}

case "$BROWSER_TYPE" in
    chromium)
        detect_cookie "chromium" "$HOME/snap/chromium/common/chromium" "WSL Chromium" || true
        ;;
    edge)
        WIN_USER=$(ls /mnt/c/Users/ 2>/dev/null | grep -v "Public\|Default\|All Users" | head -1)
        if [ -n "$WIN_USER" ]; then
            detect_cookie "edge" "C:/Users/$WIN_USER/AppData/Local/Microsoft/Edge/User Data" "Windows Edge" || true
        fi
        ;;
    firefox)
        detect_cookie "firefox" "$HOME/snap/firefox/common/.mozilla/firefox" "WSL Firefox" || true
        ;;
esac

if [ ${#COOKIE_ARGS[@]} -eq 0 ]; then
    # WSL 环境
    detect_cookie "chromium" "$HOME/snap/chromium/common/chromium" "WSL Chromium" || \
    { WIN_USER=$(ls /mnt/c/Users/ 2>/dev/null | grep -v "Public\|Default\|All Users" | head -1); \
      [ -n "$WIN_USER" ] && detect_cookie "edge" "C:/Users/$WIN_USER/AppData/Local/Microsoft/Edge/User Data" "Windows Edge"; } || \
    detect_cookie "firefox" "$HOME/snap/firefox/common/.mozilla/firefox" "WSL Firefox" || \
    # 原生 Linux
    detect_cookie "chromium" "$HOME/.config/chromium" "Chromium" || \
    detect_cookie "chrome" "$HOME/.config/google-chrome" "Chrome" || \
    detect_cookie "firefox" "$HOME/.mozilla/firefox" "Firefox" || \
    detect_cookie "brave" "$HOME/.config/BraveSoftware/Brave-Browser" "Brave" || true
fi

if [ ${#COOKIE_ARGS[@]} -eq 0 ]; then
    echo "   ⚠️ 无可用Cookie，B站AI字幕可能无法获取"
    echo "   💡 请先用 chromium-browser 登录 bilibili.com"
else
    if [ -n "$DETECTED_COOKIE_PATH" ] && [ -f "$DETECTED_COOKIE_PATH" ]; then
    COOKIE_AGE=$(ls -lu "$DETECTED_COOKIE_PATH" 2>/dev/null | awk '{print $6, $7}')
    echo "   ℹ️  Cookie最后使用: $COOKIE_AGE（约30天过期）"
else
    COOKIE_AGE=$(ls -lu "$HOME/snap/chromium/common/chromium/Default/Cookies" 2>/dev/null | awk '{print $6, $7}')
    echo "   ℹ️  Cookie最后使用: $COOKIE_AGE（约30天过期）"
fi
fi
echo ""

# ===== 获取视频元数据 =====
VIDEO_INFO=$(yt-dlp "${COOKIE_ARGS[@]}" --dump-json "$VIDEO_URL" 2>/dev/null | head -1)

if [ -z "$VIDEO_INFO" ]; then
    VIDEO_INFO=$(yt-dlp --dump-json "$VIDEO_URL" 2>/dev/null | head -1)
    if [ -z "$VIDEO_INFO" ]; then
        echo "❌ 无法获取视频信息，请检查网络或链接是否正确"
        exit 1
    fi
fi

TITLE=$(echo "$VIDEO_INFO" | python3 -c "import sys, json; print(json.load(sys.stdin).get('title', '未知标题'))")
AUTHOR=$(echo "$VIDEO_INFO" | python3 -c "import sys, json; print(json.load(sys.stdin).get('uploader', '未知作者'))")
UPLOAD_DATE=$(echo "$VIDEO_INFO" | python3 -c "import sys, json; print(json.load(sys.stdin).get('upload_date', '未知时间'))")
DURATION_SEC=$(echo "$VIDEO_INFO" | python3 -c "import sys, json; print(json.load(sys.stdin).get('duration', 0))")
DURATION=$(echo "$VIDEO_INFO" | python3 -c "import sys, json; d=json.load(sys.stdin).get('duration', 0); print(f'{int(d//60)}分{int(d%60)}秒')")
VIDEO_ID=$(echo "$VIDEO_INFO" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', ''))")

if [ "$UPLOAD_DATE" != "未知时间" ]; then
    UPLOAD_DATE_FORMATTED=$(echo "$UPLOAD_DATE" | sed 's/\(....\)\(..\)\(..\)/\1-\2-\3/')
else
    UPLOAD_DATE_FORMATTED="$UPLOAD_DATE"
fi

echo "📹 视频: $TITLE"
echo "👤 作者: $AUTHOR"
echo "📅 发布: $UPLOAD_DATE_FORMATTED"
echo "⏱️  时长: $DURATION"
shell_log "INFO" "开始转录: $VIDEO_URL | $TITLE | $AUTHOR"

# ===== 检查字幕 =====
echo ""
echo "🔍 正在检查字幕..."
SUB_CHECK=$(yt-dlp "${COOKIE_ARGS[@]}" --list-subs "$VIDEO_URL" 2>&1)

HAS_CC_SUBS=false
CC_SUB_LANG=""
CC_SUB_LANG=$(echo "$SUB_CHECK" | awk '!/danmaku/ && !/ai-/ && /^[[:space:]]*(zh-CN|zh-TW|zh-Hans|zh-Hant|en|ja|ko|es|ar|pt|de|fr)($|[-[:space:]])/ {print $1; exit}')
if [ -n "$CC_SUB_LANG" ]; then
    HAS_CC_SUBS=true
fi

HAS_AI_SUBS=false
AI_LANG=""
for lang in "ai-zh" "ai-en" "ai-ja" "ai-kr" "ai-th" "ai-id" "ai-vi"; do
    if echo "$SUB_CHECK" | grep -q "$lang"; then
        HAS_AI_SUBS=true
        AI_LANG="$lang"
        break
    fi
done

TRANSCRIPT_SOURCE=""
TRANSCRIPT_TEXT=""

# 第1级：人工CC字幕
if [ "$HAS_CC_SUBS" = true ]; then
    echo "✅ 发现人工CC字幕（$CC_SUB_LANG），优先下载..."

    yt-dlp "${COOKIE_ARGS[@]}" --skip-download --write-subs --sub-langs "$CC_SUB_LANG" --convert-subs srt \
        -o "${OUTPUT_DIR}/bilibili_subtitle.%(ext)s" "$VIDEO_URL" 2>&1

    SUB_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 -name "bilibili_subtitle*.srt" -type f 2>/dev/null | head -1)

    if [ -n "$SUB_FILE" ] && [ -s "$SUB_FILE" ]; then
        echo "✅ CC字幕下载成功"
        TRANSCRIPT_SOURCE="B站CC字幕"
        shell_log "SUCCESS" "使用CC字幕 ($CC_SUB_LANG)"
        TRANSCRIPT_TEXT=$(sed '/^[0-9]\{1,\}:[0-9][0-9]:[0-9][0-9]/d' "$SUB_FILE" | sed '/^[0-9]*$/d' | sed '/^$/d')
    else
        echo "⚠️  CC字幕下载失败..."
        HAS_CC_SUBS=false
    fi
fi

# 第2级：AI字幕
if [ -z "$TRANSCRIPT_TEXT" ] && [ "$HAS_AI_SUBS" = true ]; then
    echo "✅ 发现AI字幕（$AI_LANG），正在下载..."

    yt-dlp "${COOKIE_ARGS[@]}" --skip-download --write-subs --write-auto-subs --sub-langs "$AI_LANG" --convert-subs srt \
        -o "${OUTPUT_DIR}/bilibili_ai_subtitle.%(ext)s" "$VIDEO_URL" 2>&1

    SUB_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 -name "bilibili_ai_subtitle*.srt" -type f 2>/dev/null | head -1)

    if [ -n "$SUB_FILE" ] && [ -s "$SUB_FILE" ]; then
        echo "✅ AI字幕下载成功"
        TRANSCRIPT_SOURCE="B站AI字幕 ($AI_LANG)"
        shell_log "SUCCESS" "使用AI字幕 ($AI_LANG)"
        TRANSCRIPT_TEXT=$(sed '/^[0-9]\{1,\}:[0-9][0-9]:[0-9][0-9]/d' "$SUB_FILE" | sed '/^[0-9]*$/d' | sed '/^$/d')
    else
        echo "⚠️  AI字幕下载失败..."
        HAS_AI_SUBS=false
    fi
fi

# 第2.5级：兜底 - 尝试直接下载AI字幕（解决 yt-dlp 列表检测不到的 AI 字幕）
if [ -z "$TRANSCRIPT_TEXT" ]; then
    echo "🔍 尝试直接下载 AI 字幕（兜底）..."
    for try_lang in "ai-zh" "ai-en" "ai-ja"; do
        yt-dlp "${COOKIE_ARGS[@]}" --skip-download --write-subs --write-auto-subs --sub-langs "$try_lang" --convert-subs srt \
            -o "${OUTPUT_DIR}/bilibili_ai_subtitle.%(ext)s" "$VIDEO_URL" 2>/dev/null
        SUB_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 -name "bilibili_ai_subtitle*.srt" -type f 2>/dev/null | head -1)
        if [ -n "$SUB_FILE" ] && [ -s "$SUB_FILE" ]; then
            echo "✅ 兜底成功！AI字幕已下载（$try_lang）"
            TRANSCRIPT_SOURCE="B站AI字幕 ($try_lang)"
            shell_log "SUCCESS" "兜底AI字幕 ($try_lang)"
            TRANSCRIPT_TEXT=$(sed '/^[0-9]\{1,\}:[0-9][0-9]:[0-9][0-9]/d' "$SUB_FILE" | sed '/^[0-9]*$/d' | sed '/^$/d')
            break
        fi
    done
fi

# ===== 初始化 Python 和脚本路径（Whisper 和后续 DB 操作都需要） =====
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY_BIN="$SCRIPT_DIR/../.venv/bin/python3"
[ -x "$PY_BIN" ] || PY_BIN="python3"

# 第3级：Whisper 本地语音转文字
# 有独显且显存≥6GB → medium；有独显但显存<6GB → small
# 无独显且视频≤30分钟 → base；无独显且视频>30分钟 → tiny
if [ -z "$TRANSCRIPT_TEXT" ]; then
    echo "🎤 未发现字幕，使用 Whisper 本地语音转文字..."
    echo "⏳ 这可能需要一些时间，请耐心等待..."

    # 检测 CUDA 可用性
    HAS_CUDA=false
    GPU_VRAM_MB=0
    if "$PY_BIN" -c "import torch; print(torch.cuda.is_available())" 2>/dev/null | grep -q "True"; then
        HAS_CUDA=true
        GPU_NAME=$("$PY_BIN" -c "import torch; print(torch.cuda.get_device_name(0))" 2>/dev/null)
        echo "   ✅ GPU加速可用（CUDA）"
        echo "   🖥️  GPU: $GPU_NAME"
        # 检测显存
        if command -v nvidia-smi &>/dev/null; then
            GPU_VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -dc '0-9')
            GPU_VRAM_MB=${GPU_VRAM_MB:-0}
            echo "   💾 显存: ${GPU_VRAM_MB}MB"
        fi
    fi

    # 下载音频
    echo "   ⬇️ 下载音频..."
    yt-dlp "${COOKIE_ARGS[@]}" -x --audio-format mp3 -o "${OUTPUT_DIR}/bilibili_audio.%(ext)s" "$VIDEO_URL" 2>&1 || \
    yt-dlp -x --audio-format mp3 -o "${OUTPUT_DIR}/bilibili_audio.%(ext)s" "$VIDEO_URL" 2>&1

    AUDIO_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 \( -name "bilibili_audio*.mp3" -o -name "bilibili_audio*.m4a" \) 2>/dev/null | head -1)

    if [ -z "$AUDIO_FILE" ]; then
        echo "❌ 音频下载失败"
        exit 1
    fi

    # 转为16kHz单声道WAV（Whisper处理更快更省内存）
    echo "   🔄 音频格式优化（16kHz 单声道）..."
    WAV_FILE="${OUTPUT_DIR}/bilibili_audio.wav"
    ffmpeg -y -i "$AUDIO_FILE" -ar 16000 -ac 1 "$WAV_FILE" 2>/dev/null

    if [ -f "$WAV_FILE" ] && [ -s "$WAV_FILE" ]; then
        AUDIO_FILE="$WAV_FILE"
        echo "   ✅ 音频已优化"
    fi

    # 检查 Whisper 是否安装（优先用 venv 中的）
    WHISPER_BIN="$SCRIPT_DIR/../.venv/bin/whisper"
    [ -x "$WHISPER_BIN" ] || WHISPER_BIN="whisper"
    if ! command -v "$WHISPER_BIN" &>/dev/null; then
        echo "❌ Whisper 未安装，请运行: $SCRIPT_DIR/../.venv/bin/pip install openai-whisper"
        exit 1
    fi

    # 根据 GPU/显存选择 Whisper 模型
    #   GPU+显存≥6GB → medium | GPU+显存<6GB → small
    #   CPU+≤30分钟 → base     | CPU+>30分钟 → tiny
    DURATION_INT=${DURATION_SEC%%.*}
    DURATION_INT=${DURATION_INT:-0}
    WHISPER_MODEL="base"
    if [ "$HAS_CUDA" = true ] && [ "$GPU_VRAM_MB" -ge 6144 ]; then
        WHISPER_MODEL="medium"
        echo "   📐 GPU显存充足(≥6GB) → 使用 medium 模型（高质量）"
    elif [ "$HAS_CUDA" = true ]; then
        WHISPER_MODEL="small"
        echo "   📐 GPU显存不足(<6GB) → 使用 small 模型"
    elif [ "$DURATION_INT" -gt 1800 ]; then
        WHISPER_MODEL="tiny"
        echo "   📐 长视频(>30分钟)+CPU → 使用 tiny 模型（避免等待过久）"
    else
        WHISPER_MODEL="base"
        echo "   📐 CPU模式 → 使用 base 模型"
    fi

    # 检测视频语言（判断是否为中文内容）
    WHISPER_LANG=""
    if echo "$TITLE" | "$PY_BIN" -c "import sys; s=sys.stdin.read(); sys.exit(0 if any('\u4e00'<=c<='\u9fff' for c in s) else 1)"; then
        WHISPER_LANG="zh"
        echo "   🌐 检测到中文标题，指定 --language zh 提高准确率"
    fi

    # 运行Whisper
    WHISPER_ARGS=("$AUDIO_FILE" --model "$WHISPER_MODEL" --output_format txt --output_dir "$OUTPUT_DIR")
    if [ -n "$WHISPER_LANG" ]; then
        WHISPER_ARGS+=(--language "$WHISPER_LANG")
    fi

    echo "   🎤 开始语音转文字（模型: $WHISPER_MODEL）..."
    "$WHISPER_BIN" "${WHISPER_ARGS[@]}" 2>&1

    TXT_FILE="${OUTPUT_DIR}/bilibili_audio.txt"
    if [ ! -f "$TXT_FILE" ]; then
        TXT_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 -name "*bilibili_audio*.txt" -type f 2>/dev/null | head -1)
    fi

    if [ -n "$TXT_FILE" ] && [ -s "$TXT_FILE" ]; then
        echo "✅ 转录完成"
        TRANSCRIPT_SOURCE="Whisper $WHISPER_MODEL 模型"
        if [ "$HAS_CUDA" = true ]; then
            TRANSCRIPT_SOURCE="$TRANSCRIPT_SOURCE（GPU加速）"
        fi
        shell_log "SUCCESS" "使用Whisper $WHISPER_MODEL 转录完成"
        TRANSCRIPT_TEXT=$(cat "$TXT_FILE")
        rm -f "$TXT_FILE"
    else
        echo "❌ Whisper 转录失败"
        # 清理临时文件
        rm -f "$WAV_FILE" "$AUDIO_FILE"
        exit 1
    fi
fi

# 繁体转简体
if command -v opencc >/dev/null 2>&1; then
    echo "🔄 正在转换为简体字..."
    TRANSCRIPT_TEXT_SIMPLIFIED=$(echo "$TRANSCRIPT_TEXT" | opencc -c tw2s)
else
    TRANSCRIPT_TEXT_SIMPLIFIED="$TRANSCRIPT_TEXT"
fi

# 按发布年月组织输出目录
PUB_YEAR=$(echo "$UPLOAD_DATE_FORMATTED" | cut -d'-' -f1)
PUB_MONTH=$(echo "$UPLOAD_DATE_FORMATTED" | cut -d'-' -f2)
if [ -n "$PUB_YEAR" ] && [ "$PUB_YEAR" != "未知时间" ]; then
    OUTPUT_DIR="${OUTPUT_DIR}/${PUB_YEAR}/${PUB_MONTH}"
    mkdir -p "$OUTPUT_DIR"
fi

echo "📝 正在写入数据库..."

# ===== 第一步：写入SQLite（DB是数据源） =====
BVID=$(echo "$VIDEO_URL" | grep -oP 'BV[a-zA-Z0-9]+' | head -1)
if [ -n "$BVID" ]; then
    # 将元数据写入临时 JSON 文件（避免 shell 字符串拼接导致注入）
    META_JSON=$(mktemp /tmp/bili_meta_XXXXXX.json)
    "$PY_BIN" -c "
import json, sys
data = {
    'bvid': sys.argv[1], 'url': sys.argv[2],
    'title': sys.argv[3], 'author': sys.argv[4],
    'duration': sys.argv[5], 'upload_date': sys.argv[6],
    'transcript_source': sys.argv[7]
}
with open(sys.argv[8], 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
" "$BVID" "$VIDEO_URL" "$TITLE" "$AUTHOR" "$DURATION" "$UPLOAD_DATE_FORMATTED" "$TRANSCRIPT_SOURCE" "$META_JSON" 2>/dev/null

    # 读取 JSON 并写入 DB（全文通过 stdin 传入）
    "$PY_BIN" -c "
import sys, json; sys.path.insert(0, '$SCRIPT_DIR')
from transcript_db import TranscriptDB
with open('$META_JSON') as f:
    meta = json.load(f)
text = sys.stdin.read()
with TranscriptDB() as db:
    db.insert(
        bvid=meta['bvid'], url=meta['url'],
        title=meta['title'], author=meta['author'],
        duration=meta['duration'], upload_date=meta['upload_date'],
        transcript_source=meta['transcript_source'],
        transcript_file='', transcript_text=text, status='transcribed'
    )
    print('📝 已写入数据库')
" <<< "$TRANSCRIPT_TEXT_SIMPLIFIED" 2>&1
    shell_log "INFO" "已写入数据库: $BVID"
    rm -f "$META_JSON"
fi

# ===== 第二步：生成AI摘要（有API key时，从DB读取） =====
if [ -n "$OPENAI_API_KEY" ] || [ -f "$SCRIPT_DIR/../.env" ]; then
    echo ""
    echo "🤖 正在生成AI摘要..."
    # 仅在未设置API key时才从.env加载（尊重已存在的环境变量）
    if [ -z "$OPENAI_API_KEY" ] && [ -f "$SCRIPT_DIR/../.env" ]; then
        set -a; . "$SCRIPT_DIR/../.env" 2>/dev/null || true; set +a
    fi
    if [ -n "$BVID" ]; then
        "$PY_BIN" "$SCRIPT_DIR/generate_summary.py" --bvid "$BVID" 2>&1
        shell_log "INFO" "AI摘要已触发: $BVID"
    fi
fi

# ===== 第三步：从DB渲染TXT（TXT是展示层） =====
if [ -n "$BVID" ]; then
    RENDERED=$("$PY_BIN" -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR')
from transcript_db import TranscriptDB
with TranscriptDB() as db:
    path = db.render_txt('$BVID')
    if path: print(path)
" 2>/dev/null)
    [ -n "$RENDERED" ] && OUTPUT_FILE="$RENDERED"
fi

echo ""
echo "✅ 转录完成！"
shell_log "SUCCESS" "转录流程完成: $BVID ($TRANSCRIPT_SOURCE)"
if [ -n "$OUTPUT_FILE" ]; then
    echo "📄 文件已保存: $OUTPUT_FILE"
    echo "$OUTPUT_FILE"
else
    echo "📄 转录全文已写入数据库"
fi
