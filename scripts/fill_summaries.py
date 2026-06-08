#!/usr/bin/env python3
"""
批量补摘要 — 扫描数据库中摘要为空的条目，逐个调LLM API填充。
适合通过 cronjob 定时运行，保证有API key时所有转录最终都有摘要。

用法：
  python3 fill_summaries.py              # 扫描并补全所有空摘要
  python3 fill_summaries.py --dry-run    # 只显示待处理数量，不实际调API
  python3 fill_summaries.py --stats      # 显示统计信息
"""

import argparse
import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcript_db import TranscriptDB
from generate_summary import generate_summary_by_bvid


def main():
    parser = argparse.ArgumentParser(description="批量补全视频摘要")
    parser.add_argument("--dry-run", action="store_true", help="只显示待处理数量，不调API")
    parser.add_argument("--stats", action="store_true", help="显示统计信息")
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

        if args.dry_run:
            for r in pending:
                print(f"   - {r['bvid']} | {r['title'][:30]}...")
            return 0

        success = 0
        fail = 0
        for i, record in enumerate(pending, 1):
            bvid = record["bvid"]
            title = record["title"]

            print(f"\n[{i}/{len(pending)}] {bvid} - {title[:30]}...")

            try:
                ok, summary_text = generate_summary_by_bvid(bvid)
                if ok:
                    print(f"   ✅ 摘要已生成并更新DB")
                    success += 1
                else:
                    print(f"   ❌ 摘要生成失败（可能缺少转录全文或API key）")
                    fail += 1
            except Exception as e:
                print(f"   ❌ 异常: {e}")
                fail += 1

            # 批量调用间短暂延迟，避免触发 API 限流
            if i < len(pending):
                time.sleep(1)

        print(f"\n{'='*50}")
        print(f"📊 完成: 成功 {success}, 失败 {fail}, 总计 {len(pending)}")
        return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
