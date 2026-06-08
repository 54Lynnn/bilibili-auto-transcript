#!/usr/bin/env python3
"""
批量补摘要 — 扫描数据库中摘要为空的条目，并行调LLM API填充。
适合通过 cronjob 定时运行，保证有API key时所有转录最终都有摘要。

用法：
  python3 fill_summaries.py              # 扫描并补全所有空摘要（默认5 worker）
  python3 fill_summaries.py --workers 8  # 使用8个并行worker
  python3 fill_summaries.py --dry-run    # 只显示待处理数量，不实际调API
  python3 fill_summaries.py --stats      # 显示统计信息
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcript_db import TranscriptDB
from generate_summary import generate_summary_by_bvid
from logger import log, success as log_success, warn, error as log_error

_print_lock = Lock()


def _process_one(bvid, title):
    """单个摘要生成任务（线程安全）。返回 (bvid, title, ok)"""
    try:
        ok, _ = generate_summary_by_bvid(bvid)
        with _print_lock:
            if ok:
                print(f"   ✅ {bvid} - {title[:40]}")
            else:
                print(f"   ❌ {bvid} - {title[:40]} (失败)")
        return bvid, title, ok
    except Exception as e:
        with _print_lock:
            print(f"   ❌ {bvid} - {title[:40]} (异常: {e})")
        log_error("fill_summaries", f"{bvid} 异常: {e}")
        return bvid, title, False


def main():
    parser = argparse.ArgumentParser(description="批量补全视频摘要")
    parser.add_argument("--dry-run", action="store_true", help="只显示待处理数量，不调API")
    parser.add_argument("--stats", action="store_true", help="显示统计信息")
    parser.add_argument("--workers", type=int, default=5,
                        help="并行worker数（默认5，LLM API为I/O密集型，增大可加速）")
    args = parser.parse_args()

    with TranscriptDB() as db:
        if args.stats:
            s = db.stats()
            print(f"📊 数据库统计:")
            print(f"   总记录: {s['total']}")
            print(f"   已有摘要: {s['with_summary']}")
            print(f"   待补摘要: {s['pending_summary']}")
            return 0

        pending = db.get_pending_summaries()

    if not pending:
        print("✅ 所有视频都已有摘要，无需处理")
        return 0

    print(f"📋 发现 {len(pending)} 个视频待补摘要")
    log("fill_summaries", f"开始批量补摘要，共 {len(pending)} 个待处理")

    if args.dry_run:
        for r in pending:
            print(f"   - {r['bvid']} | {r['title'][:30]}...")
        return 0

    workers = min(args.workers, len(pending))
    print(f"🔄 使用 {workers} 个并行 worker...")

    success_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_process_one, r["bvid"], r["title"]): r
            for r in pending
        }
        for future in as_completed(futures):
            bvid, title, ok = future.result()
            if ok:
                success_count += 1
            else:
                fail_count += 1

    print(f"\n{'='*50}")
    print(f"📊 完成: 成功 {success_count}, 失败 {fail_count}, 总计 {len(pending)}")
    log("fill_summaries", f"批量补摘要完成: 成功 {success_count}, 失败 {fail_count}, 总计 {len(pending)}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
