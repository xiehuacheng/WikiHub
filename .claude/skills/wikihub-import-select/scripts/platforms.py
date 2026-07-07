#!/usr/bin/env python3
"""
Platform adapters for loading xiaohongshu and bilibili favorite items.

Scripts are run from the project root, so sibling skill modules are located via
sys.path.insert before import.
"""

import json
import shutil
import subprocess
import sys
import warnings
from pathlib import Path


ROOT: Path = Path.cwd()
BILIBILI_CONFIG_FILE: Path = ROOT / "bilibili-export-config.json"
CACHE_FILE: Path = ROOT / "wikihub-favorites-cache.json"


def _load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


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

    scripts_dir = ROOT / ".claude" / "skills" / "wikihub-export-xiaohongshu" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import xhs_cli
    except Exception as e:
        warnings.warn(f"无法导入 xhs_cli: {e}")
        return []
    finally:
        # Keep path in sys.path; other modules may rely on it.
        pass

    try:
        notes = xhs_cli.list_favorite_notes()
    except Exception as e:
        print(f"⚠️  获取小红书收藏列表失败：{e}", file=sys.stderr)
        return []

    print("🌐 小红书：实时获取")

    items = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        note_id = str(note.get("note_id", ""))
        if not note_id:
            continue

        display_title = str(note.get("display_title", "") or note.get("title", ""))
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
        user = note.get("user") or {}
        author = str(user.get("nickname", "") or user.get("nickName", ""))
        cover = note.get("cover") or {}
        if isinstance(cover, dict):
            cover_url = str(cover.get("url", "") or "")
        else:
            cover_url = str(cover or "")

        interact = note.get("interact_info") or note.get("interact") or {}
        liked_count = str(interact.get("liked_count", "") or interact.get("likedCount", ""))
        stats = f"👍 {liked_count}" if liked_count else ""

        items.append({
            "platform": "xiaohongshu",
            "item_key": f"xhs_{note_id}",
            "title": display_title,
            "url": url,
            "author": author,
            "cover": cover_url,
            "duration": "",
            "stats": stats,
            "folder": "默认收藏夹",
            "source_meta": note,
        })
    return items


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

    if not shutil.which("bili"):
        print("⚠️  未检测到 bili CLI，跳过 B 站收藏夹。", file=sys.stderr)
        return []

    config = _load_json(BILIBILI_CONFIG_FILE, {"folders": []})
    folders = config.get("folders", [])
    if not folders:
        print("⚠️  未找到 bilibili-export-config.json 或未配置收藏夹。", file=sys.stderr)
        return []

    all_items = []
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        # When fetching live (for cache/sync), fetch all folders so the cache
        # contains every video; dashboard/export will filter by enabled folders.
        folder_id = str(folder.get("id", ""))
        folder_name = str(folder.get("name", "未命名"))
        if not folder_id:
            print(f"⚠️  B 站收藏夹配置缺少 id：{folder}", file=sys.stderr)
            continue

        try:
            result = subprocess.run(
                ["bili", "favorites", folder_id, "--json"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                print(
                    f"⚠️  获取 B 站收藏夹 {folder_name} ({folder_id}) 失败：{result.stderr.strip()}",
                    file=sys.stderr,
                )
                continue
            data = json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            print(f"⚠️  获取 B 站收藏夹 {folder_name} ({folder_id}) 超时。", file=sys.stderr)
            continue
        except json.JSONDecodeError as e:
            print(
                f"⚠️  解析 B 站收藏夹 {folder_name} ({folder_id}) JSON 失败：{e}",
                file=sys.stderr,
            )
            continue
        except Exception as e:
            print(f"⚠️  获取 B 站收藏夹 {folder_name} ({folder_id}) 失败：{e}", file=sys.stderr)
            continue

        videos = _extract_list(data)
        for video in videos:
            if not isinstance(video, dict):
                continue
            bvid = str(video.get("bvid", "") or video.get("id", ""))
            if not bvid:
                continue

            title = str(video.get("title", ""))
            duration = str(video.get("duration", ""))
            upper = video.get("upper") or {}
            author = str(upper.get("name", "")) if isinstance(upper, dict) else ""

            all_items.append({
                "platform": "bilibili",
                "item_key": bvid,
                "title": title,
                "url": f"https://www.bilibili.com/video/{bvid}/",
                "author": author,
                "cover": "",
                "duration": duration,
                "stats": "",
                "folder": folder_name,
                "source_meta": video,
            })

    return all_items


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
        result = subprocess.run(
            ["bili", "favorites", "--json"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if result.returncode != 0:
            print(f"⚠️  获取 B 站收藏夹列表失败：{result.stderr.strip()}", file=sys.stderr)
            return []
        data = json.loads(result.stdout)
    except Exception as e:
        print(f"⚠️  获取 B 站收藏夹列表失败：{e}", file=sys.stderr)
        return []

    raw_folders = _extract_list(data)
    return [
        {
            "id": str(f.get("id", "")),
            "name": str(f.get("name", "未命名")),
            "enabled": False,
            "target_wiki": "",
        }
        for f in raw_folders
        if isinstance(f, dict) and f.get("id")
    ]


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
        # Folder not in config: fetch from CLI and add it (default enabled).
        for folder in load_bilibili_folders():
            if folder["id"] == folder_id:
                folder["enabled"] = True
                folders.append(folder)
                new_state = True
                found = True
                break

    if not found:
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
    return source_id
