#!/usr/bin/env python3
"""
Export a single Bilibili video URL to local markdown source file.

Usage:
    python export-one.py --url "https://www.bilibili.com/video/BVxxx"
    python export-one.py --url "https://b23.tv/xxx"
"""

import argparse
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bilibili_common import (
    ROOT,
    CONFIG_FILE,
    EXPORTED_FILE,
    UNMAPPED_DIR,
    PENDING_FILE,
    load_json,
    save_json,
    slugify,
    unique_path,
    extract_bvid,
    exported_key,
    get_video_info,
    build_frontmatter,
    build_body,
    transcribe_video,
)


def resolve_b23_url(url: str) -> str:
    """解析 b23.tv 短链接，返回最终跳转后的 URL。"""
    if "b23.tv" not in url:
        return url

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    # 先尝试 HEAD 请求，失败则回退到 GET
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as resp:
                resolved = resp.geturl()
                if "bilibili.com" in resolved:
                    return resolved
        except urllib.error.HTTPError as e:
            # 某些短链接对 HEAD 返回 405，继续尝试 GET
            if method == "HEAD" and e.code == 405:
                continue
            raise RuntimeError(f"无法解析 b23.tv 短链接：{url}，{e}")
        except Exception as e:
            raise RuntimeError(f"无法解析 b23.tv 短链接：{url}，{e}")

    raise RuntimeError(f"无法从 b23.tv 短链接获取 bilibili.com 地址：{url}")


def parse_url(url: str) -> str:
    """从 URL 中提取 BVID，支持 bilibili.com 和 b23.tv。"""
    if "b23.tv" in url:
        url = resolve_b23_url(url)
    bvid = extract_bvid(url)
    if not bvid:
        raise ValueError(f"无法从 URL 中提取 BVID：{url}")
    return bvid


def load_single_export_config() -> dict:
    """加载配置。如果文件不存在或全部禁用，返回空 dict 并打印提示。"""
    if not CONFIG_FILE.exists():
        print(f"⚠️  未找到配置文件：{CONFIG_FILE}，将使用默认目标目录 Unmapped/")
        return {}

    config = load_json(CONFIG_FILE, {})
    folders = config.get("folders", [])
    enabled = [f for f in folders if f.get("enabled") is not False]
    if not enabled:
        print("⚠️  bilibili-export-config.json 中没有启用的收藏夹，将使用默认目标目录 Unmapped/")
        return {}

    return enabled[0]


def append_pending_item(item: dict):
    """读取 /tmp/wikihub-pending.json，追加 item 后写回。"""
    pending = []
    if PENDING_FILE.exists():
        try:
            data = load_json(PENDING_FILE, [])
            if isinstance(data, list):
                pending = data
        except Exception:
            pending = []
    pending.append(item)
    save_json(PENDING_FILE, pending)


def main():
    parser = argparse.ArgumentParser(description="导出单个 B 站视频并转录为 Markdown")
    parser.add_argument("--url", required=True, help="B 站视频链接，支持 bilibili.com 和 b23.tv")
    args = parser.parse_args()

    try:
        bvid = parse_url(args.url)
        print(f"🔗 解析到 BVID：{bvid}")

        cfg = load_single_export_config()
        target_wiki = cfg.get("target_wiki", "")
        folder_name = cfg.get("name", "单链接导出")
        target_dir = ROOT / target_wiki if target_wiki else UNMAPPED_DIR

        exported = load_json(EXPORTED_FILE, {})
        dedup_key = exported_key(bvid)
        if bvid in exported or dedup_key in exported:
            existing = exported.get(dedup_key) or exported.get(bvid)
            print(f"⏭  已导出，跳过：{dedup_key} -> {existing.get('path', 'unknown')}")
            return

        title, author = get_video_info(bvid)
        print(f"📺 {title} | UP: {author or '未知'}")

        video = {
            "bvid": bvid,
            "title": title,
            "upper": {"name": author},
            "duration": "",
            "duration_seconds": 0,
        }

        print("🎙 开始转录...")
        transcript = transcribe_video(bvid, timeout=600)

        target_dir.mkdir(parents=True, exist_ok=True)
        filename = slugify(title) + ".md"
        file_path = unique_path(target_dir, filename)
        rel_path = str(file_path.relative_to(ROOT))

        now = datetime.now(timezone.utc).isoformat()
        frontmatter = build_frontmatter(video, folder_name, now)
        body = build_body(
            transcript.get("title", title),
            f"https://www.bilibili.com/video/{bvid}/",
            transcript.get("text", ""),
        )

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + body)

        exported[dedup_key] = {
            "title": title,
            "path": rel_path,
            "exported_at": now,
            "source": "bilibili",
            "folder": folder_name,
        }
        save_json(EXPORTED_FILE, exported)

        append_pending_item({
            "card_id": bvid,
            "title": title,
            "url": f"https://www.bilibili.com/video/{bvid}/",
            "path": rel_path,
            "snippet": transcript.get("text", "")[:2000],
        })

        print(f"✅ 导出成功：{rel_path}")
        print(f"🔑 去重键：{dedup_key}")

    except Exception as e:
        print(f"❌ 导出失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
