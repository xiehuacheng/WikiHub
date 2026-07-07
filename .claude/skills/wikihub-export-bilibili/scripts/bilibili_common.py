#!/usr/bin/env python3
"""
B 站导出脚本公共函数。

被 export-bilibili.py（批量导出）和 export-one.py（单链接导出）共用。
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd()
CONFIG_FILE = ROOT / "bilibili-export-config.json"
EXPORTED_FILE = ROOT / "wikihub-exported.json"
UNMAPPED_DIR = ROOT / "Unmapped"
PENDING_FILE = Path("/tmp/wikihub-pending.json")
TRANSCRIBE_VENV = ROOT / ".claude" / "skills" / "wikihub-export-bilibili" / ".venv" / "bin" / "python"
TRANSCRIBE_SCRIPT = ROOT / ".claude" / "skills" / "wikihub-export-bilibili" / "scripts" / "transcribe_one_json.py"


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def slugify(text: str, max_bytes: int = 200) -> str:
    if not text:
        text = "untitled"
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    text = re.sub(r"[\s\x00-\x1f]+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    if not text:
        text = "untitled"
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore").rsplit("-", 1)[0]
    return text


def unique_path(directory: Path, filename: str) -> Path:
    base = directory / filename
    if not base.exists():
        return base
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def extract_bvid(text: str) -> str | None:
    """从 URL 或裸 BV 字符串中提取 BVID。"""
    patterns = [
        r"bilibili\.com/video/(BV[\w]+)",
        r"^(BV[\w]+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.strip())
        if match:
            return match.group(1)
    return None


def exported_key(bvid: str) -> str:
    """生成 wikihub-exported.json 中的去重键。"""
    return f"bilibili_{bvid}"


def get_video_info(bvid: str) -> tuple[str, str]:
    """通过 `bili video <bvid> --yaml` 获取视频标题与 UP 主名称。"""
    try:
        cmd = ["bili", "video", bvid, "--yaml"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)
    except Exception as e:
        print(f"   ⚠️  获取视频信息失败（{bvid}）：{e}", file=sys.stderr)
        return bvid, ""

    output = result.stdout
    title_match = re.search(r"^\s*title:\s*[\"']?(.*?)[\"']?(?:\s*#.*)?$", output, re.MULTILINE)
    title = title_match.group(1).strip().strip('"\'') if title_match else ""

    owner_match = re.search(r'^\s*owner:\s*\n((?:\s+.*\n)+)', output, re.MULTILINE)
    if owner_match:
        owner_block = owner_match.group(1)
        name_match = re.search(r"^\s*name:\s*[\"']?(.*?)[\"']?(?:\s*#.*)?$", owner_block, re.MULTILINE)
        author = name_match.group(1).strip().strip('"\'') if name_match else ""
    else:
        author = ""

    return title or bvid, author


def escape_yaml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_frontmatter(video: dict, folder_name: str, now: str) -> str:
    bvid = video.get("bvid", video.get("id", ""))
    title = str(video.get("title", ""))
    url = f"https://www.bilibili.com/video/{bvid}/"
    duration = video.get("duration", "")
    duration_seconds = video.get("duration_seconds", 0)
    upper = video.get("upper") or {}
    author = upper.get("name", "") if isinstance(upper, dict) else ""

    lines = [
        "---",
        f'bilibili_bvid: "{bvid}"',
        f'title: "{escape_yaml(title)}"',
        f'url: "{url}"',
        f'folder: "{escape_yaml(folder_name)}"',
        "tags: []",
        "ai_tags: []",
        f'duration: "{duration}"',
        f'duration_seconds: {duration_seconds}',
        f'author: "{escape_yaml(author)}"',
        f'synced_at: "{now}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def build_body(title: str, url: str, text: str) -> str:
    return f"# {title}\n\n[{url}]({url})\n\n{text}\n"


def transcribe_video(bvid: str, timeout: int = 600) -> dict:
    """调用转录脚本，返回 {title, uploader, text}。"""
    python = str(TRANSCRIBE_VENV) if TRANSCRIBE_VENV.exists() else "python3"
    cmd = [python, str(TRANSCRIBE_SCRIPT), bvid]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return json.loads(result.stdout)
