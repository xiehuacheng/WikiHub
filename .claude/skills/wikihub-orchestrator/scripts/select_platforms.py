#!/usr/bin/env python3
"""
Platform adapters for loading xiaohongshu and bilibili favorite items.

Delegates actual synchronization to the platform-specific *-fetcher skills.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path


ROOT: Path = Path.cwd()
BILIBILI_CONFIG_FILE: Path = ROOT / "bilibili-export-config.json"
CACHE_FILE: Path = ROOT / "wikihub-favorites-cache.json"

XIAOHONGSHU_SYNC_SCRIPT: Path = ROOT / ".claude" / "skills" / "xiaohongshu-fetcher" / "scripts" / "sync-favorites.py"
BILIBILI_SYNC_SCRIPT: Path = ROOT / ".claude" / "skills" / "bilibili-fetcher" / "scripts" / "sync-favorites.py"


def _load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def _sync_platform(sync_script: Path) -> list[dict]:
    """调用平台同步脚本，返回标准化条目列表。"""
    if not sync_script.exists():
        raise RuntimeError(f"同步脚本不存在：{sync_script}")

    python = shutil.which("python3") or sys.executable
    output_json = Path(tempfile.mktemp(suffix=".json", prefix="wikihub-sync-"))
    try:
        result = subprocess.run(
            [python, str(sync_script), "--output-json", str(output_json)],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        data = _load_json(output_json, [])
        if not isinstance(data, list):
            raise RuntimeError(f"同步脚本返回非数组：{type(data).__name__}")
        return data
    finally:
        try:
            output_json.unlink()
        except FileNotFoundError:
            pass


def load_cache() -> dict | None:
    """Load cached items from the local favorites cache file.

    Returns a dict {"xiaohongshu": [...], "bilibili": [...]} or None if the
    cache is missing or invalid.
    """
    if not CACHE_FILE.exists():
        return None
    data = _load_json(CACHE_FILE, None)
    if not isinstance(data, dict):
        return None
    xiaohongshu = data.get("xiaohongshu", {})
    bilibili = data.get("bilibili", {})
    if isinstance(xiaohongshu, dict) and isinstance(bilibili, dict):
        return {
            "xiaohongshu": _extract_list(xiaohongshu.get("items", xiaohongshu)),
            "bilibili": _extract_list(bilibili.get("items", bilibili)),
        }
    return None


def _extract_list(data, keys=None):
    """Extract a list from possibly nested JSON data."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    keys = keys or ["items", "data", "list", "medias", "videos"]
    for key in keys:
        if key in data:
            value = data[key]
            if isinstance(value, list):
                return value
            deeper = _extract_list(value, keys)
            if deeper:
                return deeper
    return []


def load_xiaohongshu_items(use_cache: bool = True) -> list[dict]:
    """Load xiaohongshu favorite notes and normalize them."""
    if use_cache:
        cache = load_cache()
        if cache and cache.get("xiaohongshu"):
            print("📦 小红书：使用本地缓存")
            return cache["xiaohongshu"]

    print("🌐 小红书：实时获取")
    try:
        return _sync_platform(XIAOHONGSHU_SYNC_SCRIPT)
    except Exception as e:
        print(f"⚠️  获取小红书收藏列表失败：{e}", file=sys.stderr)
        return []


def load_bilibili_items(use_cache: bool = True) -> list[dict]:
    """Load bilibili favorite videos from enabled folders and normalize them."""
    config = _load_json(BILIBILI_CONFIG_FILE, {"folders": []})
    folders = config.get("folders", [])
    enabled_folder_names = {
        str(f.get("id", "")): str(f.get("name", "未命名"))
        for f in folders
        if isinstance(f, dict) and f.get("enabled", False) and f.get("id")
    }

    if use_cache:
        cache = load_cache()
        if cache and cache.get("bilibili"):
            print("📦 B 站：使用本地缓存")
            # Filter cached items by currently enabled folders.
            return [
                item for item in cache["bilibili"]
                if item.get("folder") in enabled_folder_names.values()
            ]

    print("🌐 B 站：实时获取")
    try:
        items = _sync_platform(BILIBILI_SYNC_SCRIPT)
    except Exception as e:
        print(f"⚠️  获取 B 站收藏列表失败：{e}", file=sys.stderr)
        return []

    # When fetching live, fetch all folders so the cache contains every video;
    # dashboard/export will filter by enabled folders.
    if enabled_folder_names:
        items = [item for item in items if item.get("folder") in enabled_folder_names.values()]
    return items


def load_bilibili_folders() -> list[dict]:
    """Load Bilibili favorite folders from config file.

    Returns a list of dicts with id, name, enabled, target_wiki.
    Falls back to querying `bili favorites` if config does not exist.
    """
    config = _load_json(BILIBILI_CONFIG_FILE, {"folders": []})
    folders = config.get("folders", [])
    if folders:
        return [
            {
                "id": str(f.get("id", "")),
                "name": str(f.get("name", "未命名")),
                "enabled": bool(f.get("enabled", False)),
                "target_wiki": str(f.get("target_wiki", "")),
            }
            for f in folders
            if isinstance(f, dict) and f.get("id")
        ]

    # Config missing or empty: query CLI and return all folders disabled by default.
    if not shutil.which("bili"):
        return []
    try:
        python = shutil.which("python3") or sys.executable
        result = subprocess.run(
            [python, str(BILIBILI_SYNC_SCRIPT), "--output-json", "/tmp/wikihub-bili-folders.json"],
            capture_output=True, text=True, timeout=120, check=False,
        )
        if result.returncode != 0:
            print(f"⚠️  获取 B 站收藏夹列表失败：{result.stderr.strip()}", file=sys.stderr)
            return []
        # sync-favorites.py does not have a dedicated folders mode; when no config
        # exists it enumerates and syncs all folders. We use the output to infer
        # folder names from the first video of each folder (if any).
        # A simpler fallback: ask the user to create bilibili-export-config.json.
        warnings.warn("未找到 bilibili-export-config.json，无法枚举收藏夹列表。请从示例文件创建。")
        return []
    except Exception as e:
        print(f"⚠️  获取 B 站收藏夹列表失败：{e}", file=sys.stderr)
        return []


def toggle_bilibili_folder(folder_id: str) -> dict:
    """Toggle the enabled state of a Bilibili folder and save config."""
    config = _load_json(BILIBILI_CONFIG_FILE, {"folders": []})
    folders = config.get("folders", [])
    folder_id = str(folder_id)

    found = False
    for folder in folders:
        if isinstance(folder, dict) and str(folder.get("id", "")) == folder_id:
            folder["enabled"] = not bool(folder.get("enabled", False))
            found = True
            new_state = folder["enabled"]
            break
    else:
        # Folder not in config: cannot toggle without name; ignore.
        raise ValueError(f"未找到收藏夹：{folder_id}")

    # Ensure schema defaults for all folders.
    for folder in folders:
        folder.setdefault("source", "favorites")
        folder.setdefault("urls_file", "")

    config["folders"] = folders
    with open(BILIBILI_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    return {"id": folder_id, "enabled": new_state}


def load_all_items() -> dict[str, list[dict]]:
    """Load items from both supported platforms."""
    return {
        "xiaohongshu": load_xiaohongshu_items(),
        "bilibili": load_bilibili_items(),
    }


def build_item_key(platform: str, source_id: str) -> str:
    """Build the canonical item_key for a platform and source id."""
    if platform == "xiaohongshu":
        return f"xhs_{source_id}"
    if platform == "bilibili":
        return f"bilibili_{source_id}"
    return source_id
