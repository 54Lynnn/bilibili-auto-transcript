#!/usr/bin/env python3
"""
批量转录 B站收藏夹中的所有新视频 v2.0
功能：
  - 自动扫描收藏夹所有视频（含分页）
  - 支持断点续传（已处理视频自动跳过）
  - 自动重试失败任务
  - 生成转录报告 CSV
  - 支持 LLM 摘要自动生成（可选）

注意：请在技能虚拟环境中运行（.venv/bin/python3）。
"""
import csv
import hashlib
import os
import subprocess
import sys
import time

import requests

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.join(SKILL_DIR, "scripts", "bilibili_scanner.py")
TRANSCRIPT_SH = os.path.join(SKILL_DIR, "scripts", "bilibili_transcript.sh")
STATE_DIR = os.path.expanduser("~/.openclaw/workspace/.auto-transcript-state")
PROCESSED_FILE = os.path.join(STATE_DIR, "processed_videos.txt")
REPORT_FILE = os.path.join(STATE_DIR, "transcript_report.csv")
OUTPUT_DIR = os.path.expanduser("~/workspace/knowledge/bilibili")
MAX_RETRIES = 2      # 转录失败最大重试次数
BATCH_DELAY = 3      # 视频间延迟（秒）

os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_processed():
    processed = set()
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE) as f:
            processed = set(line.strip() for line in f if line.strip())
    return processed


def save_processed(bvid):
    with open(PROCESSED_FILE, "a") as f:
        f.write(f"{bvid}\n")


def get_content_hash(filepath):
    if not os.path.exists(filepath):
        return ""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            h.update(f.read(65536))
        return h.hexdigest()[:16]
    except Exception:
        return ""


def scan_videos():
    result = subprocess.run(
        [sys.executable, SCANNER], capture_output=True, text=True, cwd=SKILL_DIR
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"Scanner error: {result.stderr}")
        return []

    videos = []
    current = None
    for line in result.stdout.splitlines():
        if line.startswith("  - BVID:"):
            if current:
                videos.append(current)
            current = {"bvid": line.split("BVID:", 1)[1].strip()}
        elif line.startswith("    TITLE:") and current:
            current["title"] = line.split("TITLE:", 1)[1].strip()
        elif line.startswith("    DURATION:") and current:
            current["duration"] = line.split("DURATION:", 1)[1].strip()
        elif line.startswith("    UPPER:") and current:
            current["upper"] = line.split("UPPER:", 1)[1].strip()
        elif line.startswith("    PUBTIME:") and current:
            current["pubtime"] = line.split("PUBTIME:", 1)[1].strip()
    if current:
        videos.append(current)
    return videos


def transcribe_video(bvid, attempt=1, max_retries=1):
    url = f"https://www.bilibili.com/video/{bvid}/"
    print(f"\n{'='*70}")
    print(f"🎬 开始转录: {bvid} (尝试 {attempt}/{max_retries})")
    print(f"{'='*70}")

    result = subprocess.run(
        ["bash", TRANSCRIPT_SH, url, OUTPUT_DIR],
        capture_output=True, text=True,
        cwd=SKILL_DIR, timeout=7200
    )

    if result.stdout:
        print(result.stdout[-2000:])
    if result.stderr:
        stderr_preview = result.stderr.strip()[-500:]
        if stderr_preview:
            print(f"STDERR: {stderr_preview}")

    used_stt = "Whisper" in result.stdout or "语音转文字" in result.stdout

    if "✅ 转录完成" in result.stdout:
        saved_file = None
        for line in result.stdout.splitlines():
            if line.strip().endswith(".txt") and "/" in line:
                saved_file = line.strip()
        transcript_source = None
        for line in result.stdout.splitlines():
            if "转录来源" in line:
                transcript_source = line.replace("📝 转录来源：", "").strip()
                break
        return True, saved_file or "unknown", transcript_source or "unknown", used_stt
    else:
        error_msg = result.stdout[-300:] if result.stdout else "无输出"
        return False, error_msg, None, used_stt


def generate_summary(filepath, api_key=None, api_url=None):
    if not os.path.exists(filepath):
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if "【AI待处理" not in content:
        return False

    title = ""
    for line in content.splitlines():
        if "视频标题：" in line:
            title = line.split("视频标题：", 1)[1].strip()
            break

    text_start = content.find("第二部分：完整原文")
    if text_start == -1:
        return False

    transcript_text = content[text_start:].strip()
    transcript_text = transcript_text[:30000]

    summary = None

    if api_key:
        try:
            payload = {
                "model": llm_api_model,
                "messages": [
                    {"role": "system", "content": "你是一个视频摘要助手。请对以下转录文本生成结构化摘要，包含：1) 核心观点 2) 主要论点 3) 关键结论。用中文回复，简洁明了。"},
                    {"role": "user", "content": f"视频标题：{title}\n\n转录文本：\n{transcript_text}"}
                ],
                "max_tokens": 1024
            }
            resp = requests.post(
                api_url or "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                },
                timeout=60
            )
            resp_data = resp.json()
            summary = resp_data["choices"][0]["message"]["content"]

        except Exception as e:
            print(f"   ⚠️ LLM摘要生成失败: {e}")

    if summary:
        new_content = content.replace(
            "【AI待处理：请阅读全文后，替换此行，写结构化摘要】",
            summary.strip()
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"   ✅ AI摘要已写入")
        return True

    return False


def main():
    print("=" * 70)
    print("📼 B站收藏夹批量转录 v2.0")
    print("=" * 70)

    videos = scan_videos()
    if not videos:
        print("没有新视频需要转录")
        return 0

    processed = load_processed()
    pending = [v for v in videos if v["bvid"] not in processed]
    total = len(videos)
    remaining = len(pending)

    print(f"\n📊 总计 {total} 个视频")
    print(f"✅ 已处理 {total - remaining} 个")
    print(f"⏳ 待处理 {remaining} 个")

    if remaining == 0:
        print("🎉 全部视频已转录完成！")
        return 0

    # 读取 LLM 配置
    llm_api_key = os.environ.get("OPENAI_API_KEY", "")
    llm_api_url = os.environ.get("SUMMARY_API_URL", "")
    llm_api_model = os.environ.get("SUMMARY_API_MODEL", "gpt-4o-mini")
    enable_summary = bool(llm_api_key)

    if enable_summary:
        print(f"📝 AI摘要生成: 已启用")
    else:
        print(f"📝 AI摘要生成: 未启用（设置 OPENAI_API_KEY 环境变量可开启）")

    start_time = time.time()
    success_count = 0
    fail_count = 0
    report_rows = []

    for i, v in enumerate(pending, 1):
        bvid = v["bvid"]
        current_remaining = remaining - i + 1

        elapsed = time.time() - start_time if i > 1 else 0
        if elapsed > 0 and success_count > 0:
            avg_time = elapsed / (success_count)
            eta = avg_time * current_remaining
            print(f"\n⏱️  已用: {int(elapsed//60)}分{int(elapsed%60)}秒"
                  f" | 预计剩余: {int(eta//60)}分{int(eta%60)}秒")

        print(f"\n📌 [{total - remaining + i}/{total}] {v['title']}")
        print(f"   ⏱️  {v['duration']} | 👤 {v['upper']}")

        # 带重试的转录
        # AI 字幕/CC 字幕失败可重试（快速），Whisper 失败也直接跳过（模型加载慢）
        ok = False
        output_file = None
        transcript_source = None
        used_stt = False
        max_attempts = MAX_RETRIES + 1
        for attempt in range(1, max_attempts + 1):
            ok, output_path, transcript_source, used_stt = transcribe_video(bvid, attempt, max_attempts)
            if ok:
                output_file = output_path
                break
            if used_stt:
                print("   ⏭️ Whisper 失败，跳过重试（模型加载耗时）")
                break
            if attempt <= MAX_RETRIES:
                wait = BATCH_DELAY * attempt
                print(f"   ⏳ 等待 {wait} 秒后重试...")
                time.sleep(wait)

        if ok and output_file and output_file != "unknown":
            # 内容哈希去重检查
            content_hash = get_content_hash(output_file)

            report_rows.append({
                "bvid": bvid,
                "title": v["title"],
                "author": v["upper"],
                "duration": v["duration"],
                "source": transcript_source or "unknown",
                "output_file": output_file,
                "content_hash": content_hash,
                "status": "success",
                "attempts": attempt
            })

            success_count += 1
            save_processed(bvid)
            print(f"   ✅ [{success_count}/{remaining}] 成功! 来源: {transcript_source}")

            # AI摘要生成
            if enable_summary and output_file and output_file != "unknown":
                try:
                    generate_summary(output_file, llm_api_key, llm_api_url)
                except Exception as e:
                    print(f"   ⚠️ 摘要生成异常: {e}")

        else:
            report_rows.append({
                "bvid": bvid,
                "title": v["title"],
                "author": v["upper"],
                "duration": v["duration"],
                "source": "失败",
                "output_file": "",
                "content_hash": "",
                "status": f"failed_after_{attempt}_attempts",
                "attempts": attempt
            })

            fail_count += 1
            print(f"   ❌ [{fail_count}] 失败 (尝试{attempt}次后放弃)")

        # 视频间延迟（避免触发 B站风控）
        if i < len(pending):
            time.sleep(BATCH_DELAY)

    # 生成报告
    total_time = time.time() - start_time
    print(f"\n{'=' * 70}")
    print(f"📊 批量转录完成")
    print(f"{'=' * 70}")
    print(f"   总计: {remaining} 个")
    print(f"   成功: {success_count} 个 ✅")
    print(f"   失败: {fail_count} 个 {'❌' if fail_count else '✅'}")
    print(f"   耗时: {int(total_time//60)}分{int(total_time%60)}秒")

    if report_rows:
        with open(REPORT_FILE, "w", newline="", encoding="utf-8") as f:
            fieldnames = ["bvid", "title", "author", "duration",
                          "source", "output_file", "content_hash",
                          "status", "attempts"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report_rows)
        print(f"   📄 报告已保存: {REPORT_FILE}")

        # 按转录来源统计
        sources = {}
        for row in report_rows:
            if row["status"] == "success":
                s = row["source"]
                sources[s] = sources.get(s, 0) + 1
        print(f"\n   📝 转录来源分布:")
        for src, count in sorted(sources.items(), key=lambda x: -x[1]):
            print(f"      - {src}: {count} 个")

    # 列出失败项
    if fail_count:
        print(f"\n   ❌ 失败列表:")
        for row in report_rows:
            if row["status"] != "success":
                print(f"      - {row['bvid']} {row['title']}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
