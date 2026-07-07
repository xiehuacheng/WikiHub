#!/usr/bin/env python3
"""
通用 B 站收藏夹同步工具。

读取收藏夹配置，调用 `bili favorites <folder_id> --json` 拉取视频，
输出标准化 JSON 列表。不感知 WikiHub，不读取/写入 WikiHub 状态文件。
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


CLI = "bili"
DEFAULT_CONFIG = Path("bilibili-export-config.json")


def _load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def _run_bili(args: list[str]) -> dict:
    """调用 bili CLI 并返回 JSON。"""
    if not shutil.which(CLI):
        raise RuntimeError(f"未找到 {CLI} 命令，请先安装 bilibili-cli 并登录")

    cmd = [CLI] + args + ["--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "not_authenticated" in stderr or "登录" in stderr:
            raise RuntimeError(f"{CLI} 未登录，请先运行：bili login")
        raise RuntimeError(f"{CLI} {' '.join(args)} 失败：{stderr}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"无法解析 {CLI} 输出：{e}") from e

    if not isinstance(data, dict):
        raise RuntimeError(f"{CLI} 返回非对象：{type(data).__name__}")
    if not data.get("ok"):
        error = data.get("error", {}).get("message", "unknown error")
        raise RuntimeError(f"{CLI} 返回错误：{error}")
    return data.get("data", data)


def _extract_list(data, keys=None):
    """从可能嵌套的 JSON 中提取列表。"""
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


def list_folders() -> list[dict]:
    """枚举当前登录用户的收藏夹列表。"""
    data = _run_bili(["favorites"])
    raw_folders = _extract_list(data)
    folders = []
    for f in raw_folders:
        if isinstance(f, dict) and f.get("id"):
            folders.append({
                "id": str(f["id"]),
                "name": str(f.get("name", "未命名")),
            })
    return folders


def fetch_folder_videos(folder_id: str) -> list[dict]:
    """拉取单个收藏夹的全部视频。"""
    data = _run_bili(["favorites", folder_id])
    return _extract_list(data)


def normalize_video(video: dict, folder_name: str) -> dict | None:
    """把 bili favorites 的 video 对象转换为通用条目格式。"""
    if not isinstance(video, dict):
        return None
    bvid = str(video.get("bvid", "") or video.get("id", ""))
    if not bvid:
        return None

    title = str(video.get("title", ""))
    duration = str(video.get("duration", ""))
    upper = video.get("upper") or {}
    author = str(upper.get("name", "")) if isinstance(upper, dict) else ""

    return {
        "platform": "bilibili",
        "item_key": f"bilibili_{bvid}",
        "title": title,
        "url": f"https://www.bilibili.com/video/{bvid}/",
        "author": author,
        "cover": "",
        "duration": duration,
        "stats": "",
        "folder": folder_name,
        "source_meta": video,
    }


def load_config_folders(config_path: Path) -> list[dict]:
    """从配置文件中读取收藏夹，只返回 enabled 的项；若文件不存在则返回空列表。"""
    config = _load_json(config_path, {"folders": []})
    folders = config.get("folders", [])
    enabled = []
    for f in folders:
        if isinstance(f, dict) and f.get("id") and f.get("enabled", False):
            enabled.append({
                "id": str(f["id"]),
                "name": str(f.get("name", "未命名")),
            })
    return enabled


def main() -> int:
    parser = argparse.ArgumentParser(description="B 站收藏夹同步工具")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"收藏夹配置文件路径（默认：{DEFAULT_CONFIG}）",
    )
    parser.add_argument(
        "--output-json",
        required=True,
        help="输出 JSON 文件路径，内容为条目数组",
    )
    args = parser.parse_args()

    try:
        folders = load_config_folders(args.config)
        if not folders:
            # 没有配置时枚举全部收藏夹并同步所有
            print("未找到启用状态的收藏夹配置，将同步所有收藏夹", file=sys.stderr)
            folders = list_folders()

        all_items = []
        for folder in folders:
            videos = fetch_folder_videos(folder["id"])
            for video in videos:
                item = normalize_video(video, folder["name"])
                if item:
                    all_items.append(item)
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(all_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ B 站收藏夹同步完成：{len(all_items)} 条 -> {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
