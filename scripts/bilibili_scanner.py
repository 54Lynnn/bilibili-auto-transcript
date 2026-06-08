#!/usr/bin/env python3
"""
B站收藏夹快速扫描脚本 - 只扫描，不转录
输出新视频列表供 AI Agent 处理（生成摘要、通知等）
自动分页，确保收藏夹中所有视频都被扫描。

输出 JSON 格式，便于程序解析。

注意：请在技能虚拟环境中运行（.venv/bin/python3）。
"""

import json
import os
import sys

try:
    from dotenv import load_dotenv
    SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(SKILL_DIR, ".env"))
except Exception:
    pass

import requests

FAV_MEDIA_ID = os.environ.get("FAV_MEDIA_ID", "")  # 从 .env 或环境变量读取，必须配置
STATE_DIR = os.path.expanduser("~/.openclaw/workspace/.auto-transcript-state")
PROCESSED_FILE = os.path.join(STATE_DIR, "processed_videos.txt")
API_BASE = "https://api.bilibili.com/x/v3/fav/resource/list"


def fetch_all_medias():
    """分页获取收藏夹中的所有视频"""
    all_medias = []
    pn = 1
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    while True:
        url = f"{API_BASE}?media_id={FAV_MEDIA_ID}&ps=20&pn={pn}"
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(json.dumps({"error": f"网络请求失败 - {e}"}))
            sys.exit(1)
        except ValueError as e:
            print(json.dumps({"error": f"API响应解析失败 - {e}"}))
            sys.exit(1)

        if data.get("code") != 0:
            print(json.dumps({"error": f"B站API返回错误 - {data.get('message', '未知')}"}))
            sys.exit(1)

        medias = data["data"].get("medias", [])
        all_medias.extend(medias)

        if not data["data"].get("has_more"):
            break
        pn += 1

    return all_medias


def main():
    if not FAV_MEDIA_ID:
        print(json.dumps({"error": "请先设置收藏夹ID！编辑 .env 文件，设置 FAV_MEDIA_ID"}))
        return 1

    os.makedirs(STATE_DIR, exist_ok=True)

    # 分页获取收藏夹所有视频
    medias = fetch_all_medias()

    # 加载已处理记录
    processed = set()
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE) as f:
            processed = set(line.strip() for line in f if line.strip())

    # 找出新视频
    new_videos = []
    for m in medias:
        bvid = m.get("bvid", "") or m.get("bv_id", "")
        if not bvid:
            continue
        if bvid not in processed:
            new_videos.append({
                "bvid": bvid,
                "title": m.get("title", ""),
                "duration": m.get("duration", 0),
                "upper": m.get("upper", {}).get("name", ""),
                "pubtime": m.get("pubtime", 0),
            })

    output = {
        "collection_total": len(medias),
        "processed": len(processed),
        "new_videos": new_videos,
    }

    if not new_videos:
        output["status"] = "all_caught_up"
    else:
        output["status"] = f"new_videos:{len(new_videos)}"

    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
