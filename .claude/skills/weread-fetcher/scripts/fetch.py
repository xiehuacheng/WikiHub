#!/usr/bin/env python3
"""
通用微信读书笔记获取工具。

用法：
    python3 fetch.py --config config.json --output-dir ./out
    python3 fetch.py --config config.json --output-dir ./out --book-id BOOK_ID

该工具不感知 WikiHub，不读取/写入任何 WikiHub 特定状态文件。
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GATEWAY = "https://i.weread.qq.com/api/agent/gateway"
DEFAULT_SKILL_VERSION = "1.0.4"
DEFAULT_SOURCE = "notebooks"


def _load_env_file(path: Path) -> None:
    """从 KEY=VALUE 格式的 .env 文件加载环境变量（不覆盖已存在的变量）。"""
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                if (
                    len(value) >= 2
                    and value[0] == value[-1]
                    and value[0] in ('"', "'")
                ):
                    value = value[1:-1]
                if key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


# 加载当前工作目录 .env（通用工具不假设项目根目录）
_load_env_file(Path.cwd() / ".env")


def get_api_key(config_key: str | None = None) -> str:
    """获取 API Key：优先配置值，其次环境变量，最后 .env。"""
    key = (config_key or "").strip()
    if not key:
        key = os.environ.get("WEREAD_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "未设置 WEREAD_API_KEY。请在 --config 中配置 api_key，"
            "或在环境变量 / 当前目录 .env 中设置。"
        )
    return key


def call_api(
    api_name: str,
    api_key: str,
    skill_version: str = DEFAULT_SKILL_VERSION,
    **params,
) -> dict:
    """向 WeRead Agent Gateway 发起一次 POST 调用并返回 JSON。"""
    payload = {"api_name": api_name, "skill_version": skill_version}
    payload.update(params)

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        GATEWAY,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"WeRead API 调用失败 ({api_name}): HTTP {e.code} - {body}") from e
    except Exception as e:
        raise RuntimeError(f"WeRead API 调用失败 ({api_name}): {e}") from e


def _extract_list(resp: dict | list | None, keys: tuple[str, ...] = ()) -> list:
    """从网关响应中尽量找出列表字段（容错不同字段名）。"""
    if resp is None:
        return []
    if isinstance(resp, list):
        return resp
    candidates = keys or ("books", "notebooks", "reviews", "updated", "data", "list", "items")
    for key in candidates:
        value = resp.get(key)
        if isinstance(value, list):
            return value
    return []


def list_notebooks(api_key: str, count: int = 100) -> list[dict]:
    """拉取有笔记的书籍列表，cursor 分页。"""
    notebooks: list[dict] = []
    last_sort = 0
    while True:
        params: dict[str, Any] = {"count": count}
        if last_sort:
            params["lastSort"] = last_sort

        resp = call_api("/user/notebooks", api_key, **params)
        if not isinstance(resp, dict):
            break

        batch = _extract_list(resp, ("books", "notebooks", "data", "list"))
        notebooks.extend(batch)

        if not resp.get("hasMore"):
            break
        last_sort = resp.get("sort", 0)
        if not last_sort or not batch:
            break

    return notebooks


def get_bookmarks(api_key: str, book_id: str) -> tuple[list[dict], list[dict]]:
    """拉取一本书的划线。返回 (highlights, chapters)。"""
    highlights: list[dict] = []
    chapters: list[dict] = []
    synckey = 0
    while True:
        params: dict[str, Any] = {"bookId": book_id}
        if synckey:
            params["synckey"] = synckey

        resp = call_api("/book/bookmarklist", api_key, **params)
        if not isinstance(resp, dict):
            break

        batch = resp.get("updated") or resp.get("bookmarks") or []
        highlights.extend(batch)
        chapters.extend(resp.get("chapters") or [])

        if not resp.get("hasMore"):
            break
        synckey = resp.get("synckey", 0)
        if not synckey or not batch:
            break

    return highlights, chapters


def get_reviews(api_key: str, book_id: str, count: int = 200) -> list[dict]:
    """拉取一本书的个人想法/书评。"""
    reviews: list[dict] = []
    synckey = 0
    while True:
        params: dict[str, Any] = {"bookId": book_id, "count": count}
        if synckey:
            params["synckey"] = synckey

        resp = call_api("/review/list/mine", api_key, **params)
        if not isinstance(resp, dict):
            break

        batch = _extract_list(resp, ("reviews", "data", "list"))
        reviews.extend(batch)

        if not resp.get("hasMore"):
            break
        synckey = resp.get("synckey", 0)
        if not synckey or not batch:
            break

    return reviews


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def parse_notebook(notebook: dict) -> dict:
    """从 /user/notebooks 返回的 notebook 对象中提取统一字段。"""
    book = notebook.get("book") or notebook
    book_id = str(book.get("bookId") or notebook.get("bookId") or "")
    title = _coerce_str(book.get("title") or notebook.get("title")).strip()
    author = _coerce_str(book.get("author") or notebook.get("author")).strip()
    return {
        "book_id": book_id,
        "title": title,
        "author": author,
    }


def slugify(text: str, max_bytes: int = 200) -> str:
    """将标题转换为合法文件名。"""
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
    """如果文件已存在，生成唯一文件名。"""
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


def escape_yaml(value: str) -> str:
    """对 YAML 双引号字符串中的特殊字符进行转义。"""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def build_chapter_lookup(chapters: list[dict]) -> dict[str | int, str]:
    lookup = {}
    for ch in chapters:
        uid = ch.get("chapterUid")
        if uid is not None:
            lookup[uid] = ch.get("title", "")
    return lookup


def _range_start(range_str: str) -> int:
    if not range_str:
        return 0
    try:
        return int(str(range_str).split("-")[0])
    except Exception:
        return 0


def build_markdown_body(
    book_id: str,
    meta: dict,
    highlights: list[dict],
    chapters: list[dict],
    reviews: list[dict],
) -> str:
    title = meta["title"] or "微信读书笔记"
    url = f"https://weread.qq.com/web/bookDetail/{book_id}"

    lines = [f"# {title}", ""]
    lines.append(f"[微信读书链接]({url})")
    lines.append("")

    chapter_lookup = build_chapter_lookup(chapters)
    sorted_highlights = sorted(
        highlights,
        key=lambda h: (h.get("chapterUid", 0), _range_start(h.get("range", ""))),
    )

    if sorted_highlights:
        lines.append("## 划线")
        lines.append("")
        current_chapter = None
        for hl in sorted_highlights:
            chapter_uid = hl.get("chapterUid")
            chapter_title = chapter_lookup.get(chapter_uid, "")
            if chapter_title and chapter_title != current_chapter:
                lines.append(f"### {chapter_title}")
                lines.append("")
                current_chapter = chapter_title

            mark_text = str(hl.get("markText") or hl.get("content") or "").strip()
            if not mark_text:
                continue
            create_time = hl.get("createTime", "")
            time_note = f" *({create_time})*" if create_time else ""
            lines.append(f"> {mark_text}{time_note}")
            note = str(hl.get("note") or "").strip()
            if note:
                lines.append("")
                lines.append(f"想法：{note}")
            lines.append("")

    if reviews:
        lines.append("## 我的想法")
        lines.append("")
        for review in reviews:
            content = str(review.get("content") or review.get("review") or "").strip()
            if not content:
                continue
            chapter_uid = review.get("chapterUid")
            chapter_title = chapter_lookup.get(chapter_uid, "")
            create_time = review.get("createTime", "")
            header = []
            if chapter_title:
                header.append(f"章节：{chapter_title}")
            if create_time:
                header.append(f"时间：{create_time}")
            if header:
                lines.append(f"**{' · '.join(header)}**")
                lines.append("")
            lines.append(content)
            lines.append("")

    return "\n".join(lines)


def build_frontmatter(meta: dict, now: str) -> str:
    lines = [
        "---",
        f'title: "{escape_yaml(meta["title"])}"',
        f'url: "https://weread.qq.com/web/bookDetail/{meta["book_id"]}"',
        f'author: "{escape_yaml(meta["author"])}"',
        f'fetched_at: "{now}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def export_book(
    api_key: str,
    output_dir: Path,
    meta: dict,
    source: str,
    now: str,
) -> dict:
    """导出一本书，返回结果字典。"""
    book_id = meta["book_id"]
    title = meta["title"] or book_id
    url = f"https://weread.qq.com/web/bookDetail/{book_id}"
    base_result = {
        "success": False,
        "file": None,
        "title": title,
        "url": url,
        "author": meta.get("author", ""),
        "media_files": [],
        "metadata": {"book_id": book_id, "source": source},
    }

    try:
        highlights, chapters = get_bookmarks(api_key, book_id)
        reviews = get_reviews(api_key, book_id)

        if not highlights and not reviews:
            base_result["success"] = True
            base_result["file"] = None
            return base_result

        output_dir.mkdir(parents=True, exist_ok=True)
        filename = slugify(title) + ".md"
        file_path = unique_path(output_dir, filename)

        frontmatter = build_frontmatter(meta, now)
        body = build_markdown_body(book_id, meta, highlights, chapters, reviews)
        file_path.write_text(frontmatter + body, encoding="utf-8")

        base_result["success"] = True
        base_result["file"] = str(file_path)
        return base_result
    except Exception as e:
        base_result["success"] = False
        base_result["error"] = str(e)
        return base_result


def collect_books_for_folder(
    api_key: str, folder: dict, target_book_id: str | None = None
) -> list[dict]:
    """根据 folder 配置收集书籍元数据列表。"""
    source = folder.get("source", DEFAULT_SOURCE)
    if source != "notebooks":
        return []

    notebooks = list_notebooks(api_key)
    books = []
    seen = set()
    for nb in notebooks:
        meta = parse_notebook(nb)
        book_id = meta["book_id"]
        if not book_id or book_id in seen:
            continue
        if target_book_id and book_id != target_book_id:
            continue
        seen.add(book_id)
        meta["source"] = source
        books.append(meta)
        if target_book_id:
            break
    return books


def load_config(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"配置文件不存在：{path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError("配置文件必须是 JSON 对象")
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="通用微信读书笔记获取工具")
    parser.add_argument("--config", required=True, help="JSON 配置文件路径")
    parser.add_argument("--output-dir", required=True, help="Markdown 输出目录")
    parser.add_argument("--book-id", help="只导出指定书籍")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    target_book_id = (args.book_id or "").strip() or None

    try:
        config = load_config(Path(args.config))
        api_key = get_api_key(config.get("api_key"))
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        print(json.dumps([], ensure_ascii=False))
        return 1

    now = datetime.now(timezone.utc).isoformat()
    folders = config.get("folders", [])
    enabled_folders = [f for f in folders if f.get("enabled") is not False]

    results: list[dict] = []

    if target_book_id:
        # 单书模式：从任意一个 enabled 的 notebooks folder 中定位书籍
        found = False
        for folder in enabled_folders:
            books = collect_books_for_folder(api_key, folder, target_book_id)
            if books:
                result = export_book(api_key, output_dir, books[0], folder.get("source", DEFAULT_SOURCE), now)
                results.append(result)
                found = True
                break
        if not found:
            error_result = {
                "success": False,
                "error": f"未找到 book_id 为 {target_book_id} 的书籍",
                "metadata": {"book_id": target_book_id, "source": DEFAULT_SOURCE},
            }
            results.append(error_result)
    else:
        # 批量模式：处理所有 enabled folder
        for folder in enabled_folders:
            books = collect_books_for_folder(api_key, folder)
            for book in books:
                result = export_book(api_key, output_dir, book, folder.get("source", DEFAULT_SOURCE), now)
                results.append(result)

    print(json.dumps(results, ensure_ascii=False, indent=2))

    if any(not r.get("success") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
