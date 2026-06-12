#!/usr/bin/env python3
"""
批量转录 B站收藏夹中的所有新视频 v2.1
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
import json
import os
import subprocess
import sys
import time

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(SKILL_DIR, ".env"))
except Exception:
    pass

from transcript_db import TranscriptDB
from logger import log, info, success, warn, error as log_error
SCANNER = os.path.join(SKILL_DIR, "scripts", "bilibili_scanner.py")
TRANSCRIPT_SH = os.path.join(SKILL_DIR, "scripts", "bilibili_transcript.sh")
FAV_MEDIA_ID = os.environ.get("FAV_MEDIA_ID", "")


import requests as _requests


def fetch_latest_titles(media_id: str) -> dict:
    """从收藏夹API获取所有视频的最新标题，返回 {bvid: title}"""
    if not media_id:
        return {}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"}
    titles = {}
    page = 1
    while True:
        url = f"https://api.bilibili.com/x/v3/fav/resource/list?media_id={media_id}&ps=20&pn={page}"
        try:
            resp = _requests.get(url, headers=headers, timeout=15)
            data = resp.json()
            if data.get("code") != 0:
                break
            medias = data.get("data", {}).get("medias", [])
            if not medias:
                break
            for item in medias:
                bvid = item.get("bvid", "")
                title = item.get("title", "")
                if bvid and title:
                    titles[bvid] = title
            if data.get("data", {}).get("has_more") is False:
                break
            page += 1
        except Exception:
            break
    return titles


def verify_and_fix_titles():
    """校验数据库中的标题与B站最新标题是否一致，不一致则修正"""
    latest = fetch_latest_titles(FAV_MEDIA_ID)
    if not latest:
        print("⚠️ 无法获取收藏夹最新标题，跳过校验")
        return 0

    fixed = 0
    try:
        with TranscriptDB() as db:
            rows = db.conn.execute("SELECT bvid, title FROM transcripts").fetchall()
            for row in rows:
                bvid = row["bvid"]
                db_title = row["title"]
                api_title = latest.get(bvid)
                if api_title and api_title != db_title:
                    db.conn.execute("UPDATE transcripts SET title = ? WHERE bvid = ?", (api_title, bvid))
                    db.conn.commit()
                    print(f"   🔧 标题修正: {db_title} → {api_title}")
                    fixed += 1
    except Exception as e:
        print(f"⚠️ 标题校验出错: {e}")
    return fixed
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
    if result.returncode != 0:
        print(f"Scanner error: {result.stderr}")
        return []

    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        print(f"Scanner 输出解析失败: {result.stdout[:200]}")
        return []

    if data.get("error"):
        print(f"Scanner 错误: {data['error']}")
        return []

    print(f"📊 收藏夹共 {data.get('collection_total', 0)} 个，已处理 {data.get('processed', 0)} 个")
    return data.get("new_videos", [])


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
        # 从DB读取转录来源（直接用已知bvid，无需从文件名二次提取）
        transcript_source = "unknown"
        try:
            with TranscriptDB() as db:
                record = db.get_by_bvid(bvid)
                if record:
                    transcript_source = record.get("transcript_source", "unknown")
        except Exception:
            pass
        return True, saved_file or "unknown", transcript_source, used_stt
    else:
        error_msg = result.stdout[-300:] if result.stdout else "无输出"
        return False, error_msg, None, used_stt


def main():
    print("=" * 70)
    print("📼 B站收藏夹批量转录 v2.0")
    print("=" * 70)
    info("batch_transcribe", "开始批量转录任务")

    videos = scan_videos()
    if not videos:
        print("没有新视频需要转录")
        info("batch_transcribe", "没有新视频，结束")
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

    # 显示摘要状态（摘要由shell脚本自动生成）
    if os.environ.get("OPENAI_API_KEY"):
        print(f"📝 AI摘要生成: 已启用（转录时自动生成）")
    else:
        print(f"📝 AI摘要生成: 未启用（设置 OPENAI_API_KEY 可开启）")

    start_time = time.time()
    success_count = 0
    fail_count = 0
    report_rows = []

    for i, v in enumerate(pending, 1):
        bvid = v["bvid"]
        current_remaining = remaining - i + 1

        elapsed = time.time() - start_time if i > 1 else 0
        if elapsed > 0 and (i - 1) > 0:
            avg_time = elapsed / (i - 1)  # 分母用已处理数（含失败），更准确
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
                "title": v.get("title", ""),
                "author": v.get("upper", ""),
                "duration": v.get("duration", ""),
                "source": transcript_source or "unknown",
                "output_file": output_file,
                "content_hash": content_hash,
                "status": "success",
                "attempts": attempt
            })

            success_count += 1
            save_processed(bvid)
            print(f"   ✅ [{success_count}/{remaining}] 成功! 来源: {transcript_source}")
            success("batch_transcribe", f"转录成功: {bvid} ({transcript_source})")
            # 注：shell脚本已自动完成 DB写入 + 摘要生成 + TXT渲染，此处无需重复操作

        else:
            report_rows.append({
                "bvid": bvid,
                "title": v.get("title", ""),
                "author": v.get("upper", ""),
                "duration": v.get("duration", ""),
                "source": "失败",
                "output_file": "",
                "content_hash": "",
                "status": f"failed_after_{attempt}_attempts",
                "attempts": attempt
            })

            fail_count += 1
            print(f"   ❌ [{fail_count}] 失败 (尝试{attempt}次后放弃)")
            log_error("batch_transcribe", f"转录失败: {bvid} (尝试{attempt}次)")

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
    info("batch_transcribe", f"批量转录完成: 成功 {success_count}, 失败 {fail_count}, 耗时 {int(total_time//60)}分{int(total_time%60)}秒")

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

    # 标题校验：对比B站最新标题，自动修正
    print(f"\n🔍 校验标题一致性...")
    fixed_titles = verify_and_fix_titles()
    if fixed_titles:
        print(f"   🔧 修正了 {fixed_titles} 条标题")
    else:
        print(f"   ✅ 所有标题一致")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
