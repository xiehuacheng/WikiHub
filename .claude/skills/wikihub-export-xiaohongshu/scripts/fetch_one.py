#!/usr/bin/env python3
"""
小红书单条笔记解析模块。

策略：
1. 优先通过 `xhs read <note_id>`（xiaohongshu-cli）获取笔记详情。
2. 如果 CLI 失败或返回为空，回退到 HTTP 抓取页面：
   - 优先解析 `window.__INITIAL_STATE__`
   - 失败则回退 `og:` 元标签
3. 图片/视频只保留远程链接，不下载到本地。

可被 export-xiaohongshu.py 导入使用，也可作为独立 CLI 用于调试：

    python fetch_one.py "https://www.xiaohongshu.com/explore/xxxx"

返回/输出 JSON 字段：
    note_id, title, desc, author, tags, likes, collects, comments,
    images, video_url, note_type, url
"""

import sys
import os
import re
import json
import shutil
import urllib.request
import argparse
from pathlib import Path


# 轻量 .env 加载器
ROOT = Path.cwd()


def _load_dotenv(path: Path = ROOT / ".env"):
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


_load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent))
import xhs_cli


# 小红书网页版用桌面 UA 才能拿到完整的 __INITIAL_STATE__ / noteDetailMap
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _get_cookie() -> str | None:
    """获取用于 HTTP 抓取的 cookie：环境变量 > .env > xhs CLI cookie 文件。"""
    return os.environ.get("XHS_COOKIE") or xhs_cli.get_cli_cookie()


def extract_note_id(url: str) -> str | None:
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


def http_get(url: str, cookie: str | None = None, timeout: int = 20) -> tuple[str, str]:
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
                return s[:i + 1]
    return None


def extract_initial_state(html: str) -> dict | None:
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


def _find_note(state: dict) -> dict | None:
    """从 __INITIAL_STATE__ 里定位 note 详情对象。"""
    try:
        note_map = state["note"]["noteDetailMap"]
        for v in note_map.values():
            if isinstance(v, dict) and v.get("note"):
                return v["note"]
    except Exception:
        pass

    found = [None]

    def walk(o):
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


def _extract_video_url(note: dict) -> str | None:
    """从 note.video 提取可下载的视频直链。"""
    video = note.get("video") or {}
    stream = (video.get("media") or {}).get("stream") or {}
    for codec in ("h264", "h265", "h266", "av1"):
        for item in (stream.get(codec) or []):
            if item.get("masterUrl"):
                return item["masterUrl"]
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
        "title": (note.get("title") or "").strip(),
        "desc": (note.get("desc") or "").strip().replace("\xa0", " "),
        "author": (user.get("nickName") or user.get("nickname") or "").strip(),
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
    def meta(prop):
        m = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\'](.*?)["\']',
            html, re.IGNORECASE)
        return (m.group(1).strip() if m else "")
    title = meta("og:title")
    desc = meta("og:description")
    if not title and not desc:
        return None
    return {"title": title, "desc": desc, "author": "", "tags": [],
            "likes": "", "collects": "", "comments": "", "images": [],
            "video_url": None, "note_type": "image"}


def _fetch_via_http(url: str, cookie: str | None = None) -> dict:
    """通过 HTTP 抓取页面解析笔记。"""
    print(f"  🌐 回退到 HTTP 抓取：{url}", file=sys.stderr)
    try:
        html, final_url = http_get(url, cookie)
    except Exception as e:
        raise RuntimeError(f"请求失败：{e}") from e

    state = extract_initial_state(html)
    data = None
    if state:
        note = _find_note(state)
        if note:
            data = _parse_from_state(note)
    if not data or not (data["desc"] or data["title"]):
        print("  ⚠️  结构化解析失败，回退 og 元标签", file=sys.stderr)
        data = _parse_from_meta(html) or data
    if not data or not (data["desc"] or data["title"]):
        # 如果页面被风控或笔记不可见，给出更具体的提示
        if "请通过小红书" in html or "verify" in final_url.lower():
            raise RuntimeError("被风控拦截。请设置 XHS_COOKIE 或重新运行 `xhs login`。")
        raise RuntimeError("无法解析笔记内容（页面结构可能已变化或被拦截）。")

    data["url"] = final_url
    return data


def fetch_note(url: str) -> dict:
    """获取单条小红书笔记详情。优先 CLI，失败则 HTTP 抓取。"""
    note_id = extract_note_id(url)
    if not note_id:
        raise RuntimeError(f"无法从 URL 提取 note_id：{url}")

    # 1. 先尝试 xhs CLI
    print(f"  📱 尝试通过 xhs CLI 读取：{note_id}", file=sys.stderr)
    data = xhs_cli.read_note(note_id)
    if data and (data.get("desc") or data.get("title")):
        print("  ✅ 通过 xhs CLI 获取成功", file=sys.stderr)
        data["note_id"] = note_id
        data["url"] = f"https://www.xiaohongshu.com/explore/{note_id}"
        return data

    # 2. CLI 失败，回退 HTTP 抓取
    print("  ⚠️  xhs CLI 读取失败，尝试 HTTP 抓取", file=sys.stderr)
    cookie = _get_cookie()
    if not cookie:
        print("     未找到 XHS_COOKIE，未登录访问可能被风控拦截", file=sys.stderr)
    data = _fetch_via_http(url, cookie)
    data["note_id"] = note_id
    return data


def main():
    parser = argparse.ArgumentParser(description="小红书单条笔记解析（CLI 优先，HTTP 兜底）")
    parser.add_argument("url", help="小红书笔记链接或 xhslink 短链")
    args = parser.parse_args()

    if not shutil.which("xhs"):
        print("⚠️  未检测到 xhs CLI，将直接走 HTTP 抓取", file=sys.stderr)

    try:
        data = fetch_note(args.url)
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    result = {
        "note_id": data["note_id"],
        "title": data["title"],
        "desc": data["desc"],
        "author": data["author"],
        "tags": data["tags"],
        "likes": data["likes"],
        "collects": data["collects"],
        "comments": data["comments"],
        "note_type": data["note_type"],
        "url": data["url"],
        "images": data["images"],
        "video_url": data["video_url"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
