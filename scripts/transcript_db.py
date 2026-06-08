#!/usr/bin/env python3
"""
B站视频转录 SQLite 数据库管理
存储转录元数据、全文、摘要，支持查询和更新。

用法：
  from transcript_db import TranscriptDB
  db = TranscriptDB()
  db.insert(bvid="BVxxx", title="...", ...)
  db.update_summary(bvid="BVxxx", summary="...")
  pending = db.get_pending_summaries()
"""

import os
import re
import sqlite3
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".db")
DB_PATH = os.path.join(DB_DIR, "transcripts.db")


class TranscriptDB:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.row_factory = sqlite3.Row
        self._init_table()

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bvid TEXT UNIQUE NOT NULL,
                url TEXT,
                title TEXT,
                author TEXT,
                duration TEXT,
                upload_date TEXT,
                transcript_source TEXT,
                transcript_file TEXT,
                transcript_text TEXT,
                summary TEXT,
                status TEXT DEFAULT 'transcribed',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        # 兼容旧表：补新字段
        for col, default in [("url", ""), ("transcript_text", "")]:
            try:
                self.conn.execute(f"ALTER TABLE transcripts ADD COLUMN {col} TEXT DEFAULT '{default}'")
            except sqlite3.OperationalError:
                pass
        self.conn.commit()

    def insert(self, bvid, url="", title="", author="", duration="",
               upload_date="", transcript_source="", transcript_file="",
               transcript_text="", summary="", status="transcribed"):
        """插入一条转录记录。如果 bvid 已存在则更新。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute("""
            INSERT INTO transcripts (bvid, url, title, author, duration, upload_date,
                transcript_source, transcript_file, transcript_text, summary, status,
                created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bvid) DO UPDATE SET
                url=excluded.url, title=excluded.title, author=excluded.author,
                duration=excluded.duration, upload_date=excluded.upload_date,
                transcript_source=excluded.transcript_source,
                transcript_file=excluded.transcript_file,
                transcript_text=excluded.transcript_text,
                summary=excluded.summary, status=excluded.status,
                updated_at=excluded.updated_at
        """, (bvid, url, title, author, duration, upload_date,
              transcript_source, transcript_file, transcript_text, summary, status, now, now))
        self.conn.commit()

    def update_summary(self, bvid, summary):
        """更新指定视频的摘要。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "UPDATE transcripts SET summary=?, status='summarized', updated_at=? WHERE bvid=?",
            (summary, now, bvid)
        )
        self.conn.commit()

    def update_summary_by_file(self, transcript_file, summary):
        """根据转录文件路径更新摘要。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "UPDATE transcripts SET summary=?, status='summarized', updated_at=? WHERE transcript_file=?",
            (summary, now, transcript_file)
        )
        self.conn.commit()

    def get_pending_summaries(self):
        """获取所有摘要为空的条目（需要补摘要的）。"""
        rows = self.conn.execute(
            "SELECT * FROM transcripts WHERE summary IS NULL OR summary = ''"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_bvid(self, bvid):
        """根据 bvid 查询。"""
        row = self.conn.execute("SELECT * FROM transcripts WHERE bvid=?", (bvid,)).fetchone()
        return dict(row) if row else None

    def get_all(self):
        """获取所有记录。"""
        rows = self.conn.execute("SELECT * FROM transcripts ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def stats(self):
        """统计信息。"""
        total = self.conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
        with_summary = self.conn.execute(
            "SELECT COUNT(*) FROM transcripts WHERE summary IS NOT NULL AND summary != ''"
        ).fetchone()[0]
        return {
            "total": total,
            "with_summary": with_summary,
            "pending_summary": total - with_summary
        }

    def render_txt(self, bvid, output_dir=None):
        """从DB记录渲染TXT文件。DB是数据源，TXT是展示层。"""
        record = self.get_by_bvid(bvid)
        if not record:
            return None

        output_dir = output_dir or os.path.expanduser("~/workspace/knowledge/bilibili")
        # 按发布年月组织目录
        upload_date = record.get("upload_date", "")
        if upload_date and upload_date != "未知时间":
            parts = upload_date.split("-")
            if len(parts) >= 2:
                output_dir = os.path.join(output_dir, parts[0], parts[1])
        os.makedirs(output_dir, exist_ok=True)

        # 生成安全文件名
        title = record.get("title", "untitled")
        author = record.get("author", "unknown")
        safe_title = re.sub(r'[\\/:*?"<>|]', '', title)
        safe_title = re.sub(r'[\s\W]+', '-', safe_title).strip('-')[:60] or 'untitled'
        safe_author = re.sub(r'[\\/:*?"<>|]', '', author)
        safe_author = re.sub(r'[\s\W]+', '-', safe_author).strip('-')[:30] or 'unknown'

        from datetime import datetime as _dt
        video_id = record.get("bvid", "")
        output_file = os.path.join(output_dir, f"{safe_title}_{safe_author}_{upload_date}_{video_id}.txt")

        summary = record.get("summary", "") or ""
        if summary:
            summary_block = summary.strip()
        else:
            summary_block = "【AI待处理：请阅读全文后，替换此行，写结构化摘要】"

        transcript_text = record.get("transcript_text", "") or ""
        now = record.get("created_at", _dt.now().strftime("%Y-%m-%d %H:%M:%S"))

        content = f"""================================================================================
B站视频转录文档
================================================================================

📹 视频标题：{record.get('title', '')}
🔗 B站链接：{record.get('url', '')}
👤 作者：{record.get('author', '')}
📅 发布时间：{record.get('upload_date', '')}
⏱️  视频时长：{record.get('duration', '')}
📝 转录来源：{record.get('transcript_source', '')}
⏰ 转录时间：{now}

================================================================================
第一部分：视频摘要（AI生成）
================================================================================

{summary_block}

================================================================================
第二部分：完整原文
================================================================================

{transcript_text}

================================================================================
文档结束
================================================================================
"""

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)

        # 更新文件路径
        self.conn.execute(
            "UPDATE transcripts SET transcript_file=? WHERE bvid=?",
            (output_file, bvid)
        )
        self.conn.commit()

        return output_file

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
