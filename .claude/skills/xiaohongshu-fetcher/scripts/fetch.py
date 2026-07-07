#!/usr/bin/env python3
"""
通用小红书笔记获取工具。

通过 xhs CLI 优先、HTTP 抓取兜底，将单条小红书笔记输出为 Markdown 文件，
并在 stdout 打印结果 JSON。

不依赖 WikiHub，不读取/写入任何 WikiHub 状态文件。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# xiaohongshu-cli 封装
# ---------------------------------------------------------------------------

CLI_COOKIE_FILE = Path.home() / ".xiaohongshu-cli" / "cookies.json"


def _get_cli_cookie() -> str | None:
    """从 xiaohongshu-cli 的 cookie 文件读取 Cookie 字符串，供 HTTP 回退使用。"""
    if not CLI_COOKIE_FILE.exists():
        return None
    try:
        data = json.loads(CLI_COOKIE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    cookies: list = []
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


def _run_xhs(args: list[str], timeout: int = 120) -> dict | None:
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
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data
    except Exception:
        return None


def _extract_video_url(video: dict) -> str | None:
    """从小红书 video 字段中提取视频直链。"""
    if not isinstance(video, dict):
        return None
    stream = (video.get("media") or {}).get("stream") or {}
    for codec in ("h264", "h265", "h266", "av1"):
        for item in (stream.get(codec) or []):
            if isinstance(item, dict) and item.get("masterUrl"):
                return item["masterUrl"]

    found: list[str | None] = [None]

    def walk(o: object) -> None:
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


def _extract_image_urls(image_list) -> list[str]:
    """从小红书 imageList 中提取图片 URL。"""
    urls: list[str] = []
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


def _normalize_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip().replace("\xa0", " ")


def _parse_note_from_cli(data: dict) -> dict | None:
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


def _read_note_via_cli(note_id: str) -> dict | None:
    """通过 `xhs read` 读取单条笔记详情。"""
    data = _run_xhs(["read", note_id], timeout=60)
    return _parse_note_from_cli(data)


# ---------------------------------------------------------------------------
# URL 解析与 HTTP 抓取兜底
# ---------------------------------------------------------------------------

def extract_note_id(url: str) -> str | None:
    """从小红书 URL 提取 note_id。"""
    patterns = [
        r"xiaohongshu\.com/explore/([a-zA-Z0-9]+)",
        r"xiaohongshu\.com/discovery/item/([a-zA-Z0-9]+)",
        r"xhslink\.com/([a-zA-Z0-9]+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _get_cookie() -> str | None:
    """获取用于 HTTP 抓取的 cookie：环境变量 > xhs CLI cookie 文件。"""
    return os.environ.get("XHS_COOKIE") or _get_cli_cookie()


def _http_get(url: str, cookie: str | None = None, timeout: int = 20) -> tuple[str, str]:
    """请求 URL，返回 (html, final_url)。自动跟踪 xhslink 短链跳转。"""
    headers = {"User-Agent": UA, "Referer": "https://www.xiaohongshu.com/"}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace"), resp.geturl()


def _balanced_json(s: str) -> str | None:
    """从首个 '{' 起做括号配平提取。"""
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(s):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[: i + 1]
    return None


def _extract_initial_state(html: str) -> dict | None:
    """从页面提取 window.__INITIAL_STATE__ 的 JSON。"""
    idx = html.find("__INITIAL_STATE__")
    if idx == -1:
        return None
    brace = html.find("{", idx)
    if brace == -1:
        return None
    raw = _balanced_json(html[brace:])
    if not raw:
        return None
    raw = re.sub(r"([:,\[]\s*)undefined\b", r"\1null", raw)
    try:
        return json.loads(raw)
    except Exception:
        return None


def _find_note_in_state(state: dict) -> dict | None:
    """从 __INITIAL_STATE__ 里定位 note 详情对象。"""
    try:
        note_map = state["note"]["noteDetailMap"]
        for v in note_map.values():
            if isinstance(v, dict) and v.get("note"):
                return v["note"]
    except Exception:
        pass

    found: list[dict | None] = [None]

    def walk(o: object) -> None:
        if found[0] is not None:
            return
        if isinstance(o, dict):
            if "interactInfo" in o and ("desc" in o or "title" in o):
                found[0] = o
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(state)
    return found[0]


def _parse_from_state(note: dict) -> dict:
    img_list = note.get("imageList") or []
    images = []
    for img in img_list:
        u = img.get("urlDefault") or img.get("url") or ""
        if not u:
            for info in (img.get("infoList") or []):
                if info.get("url"):
                    u = info["url"]
                    break
        if u:
            images.append(u)

    interact = note.get("interactInfo") or {}
    user = note.get("user") or {}
    video_url = _extract_video_url(note)
    return {
        "title": _normalize_text(note.get("title")),
        "desc": _normalize_text(note.get("desc")),
        "author": _normalize_text(user.get("nickName") or user.get("nickname")),
        "tags": [t.get("name", "") for t in (note.get("tagList") or []) if t.get("name")],
        "likes": str(interact.get("likedCount", "")),
        "collects": str(interact.get("collectedCount", "")),
        "comments": str(interact.get("commentCount", "")),
        "images": images,
        "video_url": video_url,
        "note_type": "video" if (note.get("type") == "video" or video_url) else "image",
    }


def _parse_from_meta(html: str) -> dict | None:
    """兜底：从 og 元标签提取标题/正文。"""

    def meta(prop: str) -> str:
        m = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\'](.*?)["\']',
            html,
            re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    title = meta("og:title")
    desc = meta("og:description")
    if not title and not desc:
        return None
    return {
        "title": title,
        "desc": desc,
        "author": "",
        "tags": [],
        "likes": "",
        "collects": "",
        "comments": "",
        "images": [],
        "video_url": None,
        "note_type": "image",
    }


def _fetch_via_http(url: str, cookie: str | None = None) -> dict:
    """通过 HTTP 抓取页面解析笔记。"""
    print(f"  回退到 HTTP 抓取：{url}", file=sys.stderr)
    try:
        html, final_url = _http_get(url, cookie)
    except Exception as e:
        raise RuntimeError(f"请求失败：{e}") from e

    state = _extract_initial_state(html)
    data = None
    if state:
        note = _find_note_in_state(state)
        if note:
            data = _parse_from_state(note)
    if not data or not (data["desc"] or data["title"]):
        print("  结构化解析失败，回退 og 元标签", file=sys.stderr)
        data = _parse_from_meta(html) or data
    if not data or not (data["desc"] or data["title"]):
        if "请通过小红书" in html or "verify" in final_url.lower():
            raise RuntimeError("被风控拦截。请设置 XHS_COOKIE 或重新运行 `xhs login`")
        raise RuntimeError("无法解析笔记内容（页面结构可能已变化或被拦截）")

    data["url"] = final_url
    return data


def fetch_note(url: str) -> dict:
    """获取单条小红书笔记详情。优先 CLI，失败则 HTTP 抓取。"""
    note_id = extract_note_id(url)
    if not note_id:
        raise RuntimeError(f"无法从 URL 提取 note_id：{url}")

    print(f"  尝试通过 xhs CLI 读取：{note_id}", file=sys.stderr)
    data = _read_note_via_cli(note_id)
    if data and (data.get("desc") or data.get("title")):
        print("  通过 xhs CLI 获取成功", file=sys.stderr)
        data["note_id"] = note_id
        data["url"] = f"https://www.xiaohongshu.com/explore/{note_id}"
        return data

    print("  xhs CLI 读取失败，尝试 HTTP 抓取", file=sys.stderr)
    cookie = _get_cookie()
    if not cookie:
        print("     未找到 XHS_COOKIE，未登录访问可能被风控拦截", file=sys.stderr)
    data = _fetch_via_http(url, cookie)
    data["note_id"] = note_id
    return data


# ---------------------------------------------------------------------------
# Markdown 生成与 CLI
# ---------------------------------------------------------------------------

def _sanitize_filename(name: str) -> str:
    """清理字符串，使其可用作文件名的一部分。"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name.strip(" ._")


def _escape_yaml(value: str) -> str:
    """简单转义 YAML frontmatter 中的字符串。"""
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return value.replace("\n", " ")


def build_markdown(data: dict) -> str:
    """根据笔记数据生成 Markdown 字符串。"""
    title = data.get("title") or "无标题"
    author = data.get("author") or ""
    url = data.get("url") or ""
    desc = data.get("desc") or ""
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        '---',
        f'title: "{_escape_yaml(title)}"',
        f'url: "{url}"',
        f'author: "{_escape_yaml(author)}"',
        f'fetched_at: "{fetched_at}"',
        '---',
        '',
        f'# {title}',
        '',
        f'[原文链接]({url})',
        '',
    ]

    if author:
        lines.append(f'> 👤 {author}')
        lines.append('')

    if desc:
        lines.append(desc)
        lines.append('')

    images = data.get("images") or []
    if images:
        lines.append('## 图片')
        lines.append('')
        for img_url in images:
            lines.append(f'![]({img_url})')
        lines.append('')

    if data.get("video_url"):
        lines.append('## 视频')
        lines.append('')
        lines.append(f'[视频链接]({data["video_url"]})')
        lines.append('')

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="通用小红书笔记获取工具")
    parser.add_argument("--url", required=True, help="小红书笔记链接")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        data = fetch_note(args.url)
    except Exception as e:
        error = {"success": False, "error": str(e)}
        print(json.dumps(error, ensure_ascii=False, indent=2))
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    note_id = data["note_id"]
    title = data.get("title") or "无标题"
    safe_title = _sanitize_filename(title)[:40]
    md_filename = f"{note_id}_{safe_title}.md" if safe_title else f"{note_id}.md"
    md_path = output_dir / md_filename

    md_content = build_markdown(data)
    md_path.write_text(md_content, encoding="utf-8")

    result = {
        "success": True,
        "file": str(md_path),
        "title": data.get("title") or "",
        "url": data.get("url") or "",
        "author": data.get("author") or "",
        "media_files": [],
        "metadata": {
            "note_id": note_id,
            "note_type": data.get("note_type") or "image",
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
