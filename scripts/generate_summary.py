#!/usr/bin/env python3
"""
AI摘要生成器 - 从DB读取转录全文，调用LLM API生成结构化摘要，更新DB。
支持两种调用方式：
  1. DB模式（推荐）：python3 generate_summary.py --bvid BVxxx
  2. 文件模式（兼容）：python3 generate_summary.py <转录文件路径>

支持环境变量（或 .env 文件）：
  OPENAI_API_KEY    — API密钥（不设置则跳过摘要）
  SUMMARY_API_URL   — API地址（默认 OpenAI）
  SUMMARY_API_MODEL — 模型名（默认 gpt-4o-mini）
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

try:
    import requests
except ImportError:
    print("错误: 请安装 requests: pip install requests", file=sys.stderr)
    sys.exit(1)

from transcript_db import TranscriptDB
from logger import log, success, warn, error as log_error


def call_llm_api(title, transcript_text, api_key, api_url, api_model):
    """调用LLM API生成摘要。返回摘要文本或None。"""
    payload = {
        "model": api_model,
        "messages": [
            {"role": "system", "content": "你是一个视频摘要助手。请对以下转录文本生成结构化摘要，包含：1) 核心观点 2) 主要论点 3) 关键结论。用中文回复，简洁明了。"},
            {"role": "user", "content": f"视频标题：{title}\n\n转录文本：\n{transcript_text[:30000]}"}
        ],
        "max_tokens": 1024
    }
    resp = requests.post(
        api_url,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        },
        timeout=60
    )
    resp.raise_for_status()
    resp_data = resp.json()
    choices = resp_data.get("choices", [])
    if not choices or "message" not in choices[0]:
        raise ValueError(f"API 返回格式异常: {resp_data}")
    return choices[0]["message"]["content"]


def get_env_config():
    """获取API配置。"""
    return {
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "api_url": os.environ.get("SUMMARY_API_URL", "https://api.openai.com/v1/chat/completions"),
        "api_model": os.environ.get("SUMMARY_API_MODEL", "gpt-4o-mini"),
    }


def generate_summary_by_bvid(bvid, api_key=None, api_url=None, api_model=None):
    """
    DB模式：从DB读取全文，生成摘要，更新DB，重渲染TXT。
    返回: (success: bool, summary_text: str | None)
    """
    config = get_env_config()
    api_key = api_key or config["api_key"]
    api_url = api_url or config["api_url"]
    api_model = api_model or config["api_model"]

    if not api_key:
        log("generate_summary", f"跳过 {bvid}: 未设置 OPENAI_API_KEY")
        return False, None

    with TranscriptDB() as db:
        record = db.get_by_bvid(bvid)
        if not record:
            return False, None

        # 已有摘要则跳过
        if record.get("summary"):
            log("generate_summary", f"{bvid} 已有摘要，跳过")
            return True, record["summary"]

        title = record.get("title", "")
        transcript_text = record.get("transcript_text", "")
        if not transcript_text:
            log("generate_summary", f"{bvid} 无转录全文，跳过")
            return False, None

        try:
            log("generate_summary", f"开始生成摘要: {bvid} - {title[:30]}")
            summary = call_llm_api(title, transcript_text, api_key, api_url, api_model)
            # 更新DB
            db.update_summary(bvid, summary.strip())
            # 重新渲染TXT（失败不阻塞：DB已有摘要，下次截断会修复）
            try:
                db.render_txt(bvid)
            except Exception as e:
                log_error("generate_summary", f"{bvid} 摘要已入库但TXT渲染失败: {e}")
            success("generate_summary", f"摘要生成成功: {bvid}")
            return True, summary
        except Exception as e:
            log_error("generate_summary", f"{bvid} 摘要生成失败: {e}")
            print(f"   ⚠️ LLM摘要生成失败: {e}", file=sys.stderr)
            return False, None


def generate_summary(filepath, api_key=None, api_url=None, api_model=None):
    """
    文件模式（兼容旧用法）：读取TXT文件，生成摘要，更新TXT。
    如果该文件对应的bvid在DB中，也更新DB。
    返回: (success: bool, summary_text: str | None)
    """
    if not os.path.exists(filepath):
        return False, None

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if "【AI待处理" not in content:
        return False, None

    config = get_env_config()
    api_key = api_key or config["api_key"]
    api_url = api_url or config["api_url"]
    api_model = api_model or config["api_model"]

    if not api_key:
        return False, None

    title = ""
    for line in content.splitlines():
        if "视频标题：" in line:
            title = line.split("视频标题：", 1)[1].strip()
            break

    text_start = content.find("第二部分：完整原文")
    if text_start == -1:
        return False, None

    transcript_text = content[text_start:].strip()

    try:
        summary = call_llm_api(title, transcript_text, api_key, api_url, api_model)

        # 更新TXT
        new_content = content.replace(
            "【AI待处理：请阅读全文后，替换此行，写结构化摘要】",
            summary.strip()
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)

        # 同步更新DB（如果该bvid存在）
        import re
        bvid_match = re.search(r'BV[a-zA-Z0-9]+', content)
        if bvid_match:
            try:
                with TranscriptDB() as db:
                    db.update_summary(bvid_match.group(0), summary.strip())
            except Exception:
                pass

        return True, summary

    except Exception as e:
        print(f"   ⚠️ LLM摘要生成失败: {e}", file=sys.stderr)
        return False, None


def main():
    parser = argparse.ArgumentParser(description="AI视频摘要生成器")
    parser.add_argument("filepath", nargs="?", help="转录TXT文件路径（文件模式）")
    parser.add_argument("--bvid", help="B站BV号（DB模式，推荐）")
    parser.add_argument("--api-key", help="API密钥（覆盖环境变量）")
    parser.add_argument("--api-url", help="API地址（覆盖环境变量）")
    parser.add_argument("--model", help="模型名（覆盖环境变量）")
    args = parser.parse_args()

    if args.bvid:
        # DB模式
        success, summary = generate_summary_by_bvid(
            args.bvid, api_key=args.api_key, api_url=args.api_url, api_model=args.model
        )
        if success:
            print(f"✅ 摘要已就绪（{args.bvid}）")
            return 0
    elif args.filepath:
        # 文件模式（兼容）
        success, summary = generate_summary(
            args.filepath, api_key=args.api_key, api_url=args.api_url, api_model=args.model
        )
        if success:
            print(f"✅ AI摘要已生成")
            return 0
    else:
        parser.print_help()
        return 1

    api_key = args.api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("ℹ️  未设置 OPENAI_API_KEY，跳过摘要生成")
    else:
        print("❌ 摘要生成失败")
    return 1


if __name__ == "__main__":
    sys.exit(main())
