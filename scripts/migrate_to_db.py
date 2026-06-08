#!/usr/bin/env python3
"""
迁移工具：将 knowledge/bilibili/ 下的旧 TXT 转录文件导入 SQLite 数据库。

用法：
    python3 migrate_to_db.py [--dry-run] [--knowledge-dir PATH]
    python3 migrate_to_db.py --stats     # 仅看 DB 统计

安全策略：
    - TXT -> DB 单向上行，不写回 TXT（不改旧文件）
    - BVID 重复自动跳过（不覆盖已有 DB 记录）
    - --dry-run 仅扫描，不写入
"""

import argparse
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from transcript_db import TranscriptDB


KNOWLEDGE_DIR = os.path.expanduser("~/workspace/knowledge/bilibili")


def parse_txt(path):
    """解析单个转录TXT文件，返回 dict 或 None"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    data = {}
    lines = content.split("\n")

    for line in lines:
        line = line.strip()
        if line.startswith("📹 视频标题："):
            data["title"] = line.replace("📹 视频标题：", "").strip()
        elif line.startswith("🔗 B站链接："):
            data["url"] = line.replace("🔗 B站链接：", "").strip()
        elif line.startswith("👤 作者："):
            data["author"] = line.replace("👤 作者：", "").strip()
        elif line.startswith("📅 发布时间："):
            data["upload_date"] = line.replace("📅 发布时间：", "").strip()
        elif line.startswith("⏱️  视频时长："):
            data["duration"] = line.replace("⏱️  视频时长：", "").strip()
        elif line.startswith("📝 转录来源："):
            data["transcript_source"] = line.replace("📝 转录来源：", "").strip()
        elif line.startswith("⏰ 转录时间："):
            data["transcribe_date"] = line.replace("⏰ 转录时间：", "").strip()

    # 提取 BVID
    bvid = None
    if data.get("url"):
        m = re.search(r"BV[a-zA-Z0-9]+", data["url"])
        if m:
            bvid = m.group(0)
    if not bvid:
        # 从文件名提取
        m = re.search(r"BV[a-zA-Z0-9]+", os.path.basename(path))
        if m:
            bvid = m.group(0)
    if not bvid:
        return None

    data["bvid"] = bvid

    # 解析摘要
    summary_header = "第一部分：视频摘要"
    transcript_header = "第二部分：完整原文"
    summary = ""
    in_summary = False
    in_transcript = False
    transcript_lines = []

    for line in lines:
        if summary_header in line:
            in_summary = True
            continue
        if transcript_header in line:
            in_summary = False
            in_transcript = True
            continue
        if "文档结束" in line:
            in_transcript = False
            continue
        if in_summary:
            stripped = line.strip()
            # 跳过空行、分隔线和占位符
            if stripped \
               and not re.match(r"^=+$", stripped) \
               and "【AI待处理" not in stripped \
               and "待处理" not in stripped:
                summary += stripped + "\n"
        if in_transcript:
            transcript_lines.append(line)

    data["summary"] = summary.strip()
    data["transcript_text"] = "\n".join(transcript_lines).strip()

    if not data.get("title"):
        data["title"] = os.path.basename(path)
    if not data.get("author"):
        data["author"] = "未知"
    if not data.get("duration"):
        data["duration"] = "未知"
    if not data.get("upload_date"):
        data["upload_date"] = "未知"

    # 将 TXT 中的 transcribe_date 映射到 DB 的 created_at
    if data.get("transcribe_date"):
        data["created_at"] = data.pop("transcribe_date")

    return data


def migrate(knowledge_dir, dry_run=False):
    """扫描 knowledge 目录，导入全部 TXT 到 DB"""
    if not os.path.isdir(knowledge_dir):
        print(f"错误: 目录不存在 {knowledge_dir}")
        return

    # 收集所有 TXT 文件
    txt_files = []
    for root, dirs, files in os.walk(knowledge_dir):
        for f in files:
            if f.endswith(".txt"):
                txt_files.append(os.path.join(root, f))

    print(f"找到 {len(txt_files)} 个转录文件")

    skipped_no_bvid = 0
    skipped_exists = 0
    imported = 0
    parsed_summary = 0
    has_summary = 0

    with TranscriptDB() as db:
        for path in txt_files:
            data = parse_txt(path)
            if not data:
                skipped_no_bvid += 1
                continue

            bvid = data["bvid"]

            if db.get_by_bvid(bvid):
                skipped_exists += 1
                continue

            if not dry_run:
                created_at = data.get("created_at", "")
                db.conn.execute(
                    """INSERT INTO transcripts
                    (bvid, url, title, author, duration, upload_date,
                     transcript_source, transcript_file,
                     transcript_text, summary, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        bvid,
                        data.get("url", ""),
                        data.get("title", ""),
                        data.get("author", ""),
                        data.get("duration", ""),
                        data.get("upload_date", ""),
                        data.get("transcript_source", ""),
                        path,
                        data.get("transcript_text", ""),
                        data.get("summary", ""),
                        created_at,
                    ),
                )
                db.conn.commit()

            imported += 1
            if data.get("summary"):
                has_summary += 1
            if data.get("transcript_source"):
                parsed_summary += 1

            print(f"  {'[DRY] ' if dry_run else ''}✓ {data['title'][:40]} ({bvid})")

    print()
    print("=" * 50)
    if dry_run:
        print(f"[DRY RUN - 未实际写入]")
    print(f"总文件数:        {len(txt_files)}")
    print(f"成功导入:        {imported}")
    print(f"已有记录跳过:    {skipped_exists}")
    print(f"无法解析BVID:    {skipped_no_bvid}")
    print(f"已有摘要:        {has_summary}")
    print(f"缺少摘要:        {imported - has_summary}")
    print(f"已有转录来源:    {parsed_summary}")


def main():
    parser = argparse.ArgumentParser(description="将旧转录TXT导入SQLite数据库")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不写入")
    parser.add_argument("--stats", action="store_true", help="显示DB统计")
    parser.add_argument("--knowledge-dir", default=KNOWLEDGE_DIR, help="knowledge目录路径")
    args = parser.parse_args()

    knowledge_dir = os.path.expanduser(args.knowledge_dir)

    if args.stats:
        with TranscriptDB() as db:
            s = db.stats()
            print(f"📊 数据库统计:")
            print(f"   总记录: {s['total']}")
            print(f"   已有摘要: {s['with_summary']}")
            print(f"   待补摘要: {s['pending_summary']}")
        return 0

    print(f"Knowledge 目录: {knowledge_dir}")
    print(f"模式: {'试运行 (不写入)' if args.dry_run else '正式导入'}")
    print()
    migrate(knowledge_dir, args.dry_run)
    return 0


if __name__ == "__main__":
    main()