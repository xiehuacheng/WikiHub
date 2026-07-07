#!/usr/bin/env python3
"""
Sync favorites data for WikiHub selection dashboard.

Fetches live data from xiaohongshu and bilibili via their respective *-fetcher
sync scripts and writes a local cache file at the project root.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT: Path = Path.cwd()
CACHE_FILE: Path = ROOT / "wikihub-favorites-cache.json"
SCRIPTS_DIR: Path = Path(__file__).resolve().parent


def sync_all() -> dict:
    """Fetch favorites from both platforms and write the local cache.

    Returns the cache dict. Raises on fetch or write errors.
    """
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import select_platforms as platforms
    except Exception as e:
        raise ImportError(f"无法导入 select_platforms: {e}") from e

    xiaohongshu_items = platforms.load_xiaohongshu_items(use_cache=False)
    bilibili_items = platforms.load_bilibili_items(use_cache=False)

    cache = {
        "version": 1,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "xiaohongshu": {"items": xiaohongshu_items},
        "bilibili": {"items": bilibili_items},
    }

    # Atomic write: write to a temp file in the same directory, then replace.
    fd, temp_path = tempfile.mkstemp(
        suffix=".json", prefix=".wikihub-favorites-cache-", dir=str(ROOT)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, CACHE_FILE)
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise

    return cache


def main() -> int:
    """Run sync and print a summary."""
    try:
        cache = sync_all()
    except Exception as e:
        print(f"❌ 同步失败：{e}", file=sys.stderr)
        return 1

    xiaohongshu_count = len(cache.get("xiaohongshu", {}).get("items", []))
    bilibili_count = len(cache.get("bilibili", {}).get("items", []))
    synced_at = cache.get("synced_at", "unknown")

    print(f"✅ 同步完成")
    print(f"   小红书：{xiaohongshu_count} 条")
    print(f"   B 站：{bilibili_count} 条")
    print(f"   时间：{synced_at}")
    print(f"   缓存：{CACHE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
