#!/usr/bin/env python3
"""
通用微信公众号文章抓取工具。

用法：
    python3 fetch.py --url "https://mp.weixin.qq.com/s/xxxxx" --output-dir ./out
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _curl(url: str, timeout: int = 30) -> str:
    """使用 curl 获取页面 HTML。"""
    result = subprocess.run(
        [
            "curl", "-sL", "--max-time", str(timeout),
            "-H", f"User-Agent: {USER_AGENT}",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=timeout + 5,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr.strip()}")
    return result.stdout


def extract_article_id(url: str) -> str:
    """从公众号 URL 提取稳定文章 ID。

    优先使用 __biz + mid + idx；fallback 到 /s/xxx 路径。
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    def _first(key: str) -> str | None:
        values = qs.get(key)
        return values[0] if values else None

    biz = _first("__biz")
    mid = _first("mid")
    idx = _first("idx")

    if biz and mid and idx:
        return f"{biz}_{mid}_{idx}"

    # fallback: /s/xxx
    match = re.search(r"/s/([^/?#]+)", parsed.path)
    if match:
        return match.group(1)

    # last resort: entire path/query fingerprint
    return re.sub(r"[^a-zA-Z0-9_-]", "_", f"{parsed.path}{parsed.query}").strip("_") or "unknown"


def fetch_article(url: str) -> dict:
    """抓取公众号文章。

    返回：
        {
            "article_id": str,
            "title": str,
            "author": str,
            "content": str,
            "url": str,
        }
    """
    print(f"Fetching: {url[:80]}...", file=sys.stderr)
    html = _curl(url)

    # 风控检测
    if "环境异常" in html or "请在微信客户端" in html:
        raise RuntimeError("Blocked by WeChat anti-bot")

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("Need beautifulsoup4: pip install beautifulsoup4") from exc

    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("h1", class_="rich_media_title")
    title = title_tag.get_text().strip() if title_tag else ""

    author_tag = soup.find("span", class_="rich_media_meta_nickname")
    author = author_tag.get_text().strip() if author_tag else ""

    content_tag = soup.find("div", class_="rich_media_content")
    if not content_tag:
        raise RuntimeError("No content found in page")

    content = content_tag.get_text()
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = content.strip()

    if len(content) < 100:
        raise RuntimeError(f"Content too short ({len(content)} chars)")

    print(f"Fetched: {title[:50]}... ({len(content)} chars)", file=sys.stderr)

    return {
        "article_id": extract_article_id(url),
        "title": title,
        "author": author,
        "content": content,
        "url": url,
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


def build_markdown(data: dict, now: str) -> str:
    """构建通用 Markdown 内容。"""
    title = str(data.get("title", "公众号文章"))
    url = data.get("url", "")
    author = str(data.get("author", ""))
    content = str(data.get("content", ""))

    frontmatter = (
        "---\n"
        f'title: "{escape_yaml(title)}"\n'
        f'url: "{url}"\n'
        f'author: "{escape_yaml(author)}"\n'
        f'fetched_at: "{now}"\n'
        "---\n\n"
    )

    lines = [f"# {title}", ""]
    if url:
        lines.append(f"[原文链接]({url})")
        lines.append("")
    if author:
        lines.append(f"> 作者：{author}")
        lines.append("")
    if content:
        lines.append(content)
    lines.append("")
    body = "\n".join(lines)

    return frontmatter + body


def main():
    parser = argparse.ArgumentParser(description="通用微信公众号文章抓取工具")
    parser.add_argument("--url", required=True, help="微信公众号文章链接，如 https://mp.weixin.qq.com/s/...")
    parser.add_argument("--output-dir", required=True, help="输出 Markdown 文件的目录")
    args = parser.parse_args()

    url = (args.url or "").strip()
    output_dir = Path(args.output_dir)

    if not url:
        print(json.dumps({"success": False, "error": "--url 不能为空"}, ensure_ascii=False))
        sys.exit(1)

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        data = fetch_article(url)
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    title = data.get("title") or data.get("article_id") or "untitled"
    filename = slugify(title) + ".md"
    file_path = unique_path(output_dir, filename)

    markdown = build_markdown(data, now)
    file_path.write_text(markdown, encoding="utf-8")

    result = {
        "success": True,
        "file": str(file_path),
        "title": data.get("title", ""),
        "url": data.get("url", ""),
        "author": data.get("author", ""),
        "media_files": [],
        "metadata": {
            "article_id": data.get("article_id", ""),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
