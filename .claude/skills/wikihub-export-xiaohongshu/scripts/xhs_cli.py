#!/usr/bin/env python3
"""
xiaohongshu-cli 封装模块。

- 调用 `xhs read <note_id> --json` 获取单条笔记详情（首选）
- 调用 `xhs favorites --json` 获取收藏列表
- 读取 `~/.xiaohongshu-cli/cookies.json` 供 HTTP 回退抓取时使用
"""

import json
import re
import shutil
import subprocess
from pathlib import Path


CLI_COOKIE_FILE = Path.home() / ".xiaohongshu-cli" / "cookies.json"


def get_cli_cookie() -> str | None:
    """从 xiaohongshu-cli 的 cookie 文件读取 Cookie 字符串，供 HTTP 回退使用。"""
    if not CLI_COOKIE_FILE.exists():
        return None
    try:
        data = json.loads(CLI_COOKIE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    cookies = []
    if isinstance(data, list):
        cookies = data
    elif isinstance(data, dict):
        cookies = data.get("cookies") or []
        if not cookies:
            return "; ".join(f"{k}={v}" for k, v in data.items())

    if not cookies:
        return None

    parts = []
    for c in cookies:
        if isinstance(c, dict):
            name = c.get("name") or c.get("Name")
            value = c.get("value") or c.get("Value")
            if name and value is not None:
                parts.append(f"{name}={value}")
        elif isinstance(c, str):
            parts.append(c)
    return "; ".join(parts) if parts else None


def _run_xhs(args: list, timeout: int = 120):
    """调用 xhs CLI，解析其 JSON 输出。"""
    if not shutil.which("xhs"):
        return None
    cmd = ["xhs"] + args + ["--json"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        # xhs CLI 输出通常是 envelope：{"ok": true, "data": ...}
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data
    except Exception:
        return None


def is_logged_in() -> bool:
    """通过 `xhs status` 或 `xhs whoami` 判断是否已登录。"""
    for cmd in (["status"], ["whoami"]):
        data = _run_xhs(list(cmd), timeout=30)
        if data is not None:
            return True
    return False


def ensure_ready():
    """检查 xhs CLI 是否已安装且已登录，否则抛出 RuntimeError。"""
    if not shutil.which("xhs"):
        raise RuntimeError(
            "未检测到 xhs CLI。请先安装并登录：\n"
            "  uv tool install xiaohongshu-cli\n"
            "  xhs login"
        )
    if not is_logged_in():
        raise RuntimeError(
            "xhs CLI 未登录。请先登录：\n"
            "  xhs login\n"
            "或：\n"
            "  xhs login --qrcode"
        )


def extract_note_id_from_url(url: str) -> str | None:
    """从小红书 URL 提取 note_id。"""
    patterns = [
        r"xiaohongshu\.com/explore/([a-zA-Z0-9]+)",
        r"xhslink\.com/([a-zA-Z0-9]+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _normalize_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip().replace("\xa0", " ")


def _extract_image_urls(image_list) -> list[str]:
    """从小红书 imageList 中提取图片 URL。"""
    urls = []
    for img in (image_list or []):
        if not isinstance(img, dict):
            if isinstance(img, str):
                urls.append(img)
            continue
        for key in ("urlDefault", "url", "originUrl", "imageUrl", "traceUrl"):
            u = img.get(key)
            if u:
                urls.append(str(u))
                break
    return urls


def _extract_video_url(video: dict) -> str | None:
    """从小红书 video 字段中提取视频直链。"""
    if not isinstance(video, dict):
        return None
    stream = (video.get("media") or {}).get("stream") or {}
    for codec in ("h264", "h265", "h266", "av1"):
        for item in (stream.get(codec) or []):
            if isinstance(item, dict) and item.get("masterUrl"):
                return item["masterUrl"]
    # 防御性遍历
    found = [None]

    def walk(o):
        if found[0] is not None:
            return
        if isinstance(o, dict):
            if isinstance(o.get("masterUrl"), str):
                found[0] = o["masterUrl"]
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(video)
    return found[0]


def parse_note_from_cli(data: dict) -> dict | None:
    """把 `xhs read` 的输出解析为统一格式。"""
    if not isinstance(data, dict):
        return None

    note = data.get("note") or data
    if not isinstance(note, dict):
        return None

    title = _normalize_text(note.get("title") or note.get("display_title"))
    desc = _normalize_text(note.get("desc") or note.get("description"))
    if not title and not desc:
        return None

    user = note.get("user") or {}
    author = _normalize_text(user.get("nickname") or user.get("nickName"))

    tags = []
    for t in (note.get("tags") or note.get("tagList") or []):
        if isinstance(t, dict):
            name = t.get("name") or t.get("tag")
            if name:
                tags.append(str(name))
        elif isinstance(t, str):
            tags.append(t)

    interact = note.get("interactInfo") or note.get("interact") or {}
    likes = str(interact.get("likedCount") or interact.get("likes") or "")
    collects = str(interact.get("collectedCount") or interact.get("collects") or "")
    comments = str(interact.get("commentCount") or interact.get("comments") or "")

    images = _extract_image_urls(note.get("imageList") or note.get("images"))
    video_url = _extract_video_url(note.get("video") or {})
    note_type = "video" if (note.get("type") == "video" or video_url) else "image"

    return {
        "title": title,
        "desc": desc,
        "author": author,
        "tags": tags,
        "likes": likes,
        "collects": collects,
        "comments": comments,
        "images": images,
        "video_url": video_url,
        "note_type": note_type,
    }


def read_note(note_id_or_url: str) -> dict | None:
    """通过 `xhs read` 读取单条笔记详情。"""
    note_id = note_id_or_url
    if "/" in note_id_or_url:
        note_id = extract_note_id_from_url(note_id_or_url) or note_id_or_url
    data = _run_xhs(["read", note_id], timeout=60)
    return parse_note_from_cli(data)


def list_favorite_urls() -> list[str]:
    """通过 `xhs favorites` 获取收藏夹中的笔记 URL 列表（全部分页）。"""
    notes = list_favorite_notes()
    urls = []
    for item in notes:
        note_id = item.get("note_id")
        url = item.get("url")
        if url:
            urls.append(url)
        elif note_id:
            urls.append(f"https://www.xiaohongshu.com/explore/{note_id}")
    return urls


def list_favorite_notes() -> list[dict]:
    """通过 `xhs favorites` 获取收藏夹中的笔记元数据列表（全部分页）。

    返回每个笔记的字典，包含 note_id, display_title, type, cover, user, interact_info 等字段。
    """
    all_notes = []
    cursor = None
    while True:
        args = ["favorites"]
        if cursor:
            args.extend(["--cursor", cursor])
        data = _run_xhs(args, timeout=120)
        if not isinstance(data, dict):
            break
        notes = data.get("notes") or []
        all_notes.extend(notes)
        if not data.get("has_more"):
            break
        cursor = data.get("cursor")
        if not cursor:
            break
    return all_notes
