#!/usr/bin/env python3
"""
B站收藏夹快速扫描脚本 - 只扫描，不转录
输出新视频列表供 AI Agent 处理（生成摘要、通知等）
自动分页，确保收藏夹中所有视频都被扫描。

注意：请在技能虚拟环境中运行（.venv/bin/python3）。
"""

import os
import sys

import requests

FAV_MEDIA_ID = "3972051046"          # ⬅️ 必填！换成你自己的B站收藏夹ID
                                     # 从收藏夹URL ?fid= 后面的数字获取
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
            print(f"ERROR: 网络请求失败 - {e}")
            sys.exit(1)
        except ValueError as e:
            print(f"ERROR: API响应解析失败 - {e}")
            sys.exit(1)

        if data.get("code") != 0:
            print(f"ERROR: B站API返回错误 - {data.get('message', '未知')}")
            sys.exit(1)

        medias = data["data"].get("medias", [])
        all_medias.extend(medias)

        if not data["data"].get("has_more"):
            break
        pn += 1

    return all_medias


def main():
    if not FAV_MEDIA_ID:
        print("ERROR: 请先设置收藏夹ID！编辑 scripts/bilibili_scanner.py，将 FAV_MEDIA_ID 改为你的收藏夹ID")
        return 1

    os.makedirs(STATE_DIR, exist_ok=True)

    # 分页获取收藏夹所有视频
    medias = fetch_all_medias()
    print(f"COLLECTION_TOTAL:{len(medias)}")

    # 加载已处理记录
    processed = set()
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE) as f:
            processed = set(line.strip() for line in f if line.strip())
    print(f"PROCESSED:{len(processed)}")

    # 找出新视频
    new_videos = []
    for m in medias:
        bvid = m.get("bvid", "") or m.get("bv_id", "")
        if not bvid:
            continue
        if bvid not in processed:
            new_videos.append({
                "bvid": bvid,
                "title": m["title"],
                "duration": m["duration"],
                "upper": m["upper"]["name"],
                "pubtime": m.get("pubtime", 0),
            })

    if not new_videos:
        print("ALL_CAUGHT_UP")
        return 0

    print(f"NEW_VIDEOS:{len(new_videos)}")
    for v in new_videos:
        mins = v["duration"] // 60
        secs = v["duration"] % 60
        print(f"  - BVID:{v['bvid']}")
        print(f"    TITLE:{v['title']}")
        print(f"    DURATION:{mins}分{secs}秒")
        print(f"    UPPER:{v['upper']}")
        print(f"    PUBTIME:{v['pubtime']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
