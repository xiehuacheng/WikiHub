#!/usr/bin/env python3
"""
微信公众号文章抓取工具。

用法：
    python fetch_article.py "https://mp.weixin.qq.com/s/xxxxx"
"""

import argparse
import re
import subprocess
import sys
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
    抓取失败或内容过短则返回 None。
    """
    print(f"  🌐 Fetching: {url[:80]}...", file=sys.stderr)
    html = _curl(url)

    # 风控检测
    if "环境异常" in html or "请在微信客户端" in html:
        print("  ❌ Blocked by WeChat", file=sys.stderr)
        return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  ❌ Need beautifulsoup4: pip install beautifulsoup4", file=sys.stderr)
        return None

    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("h1", class_="rich_media_title")
    title = title_tag.get_text().strip() if title_tag else ""

    author_tag = soup.find("span", class_="rich_media_meta_nickname")
    author = author_tag.get_text().strip() if author_tag else ""

    content_tag = soup.find("div", class_="rich_media_content")
    if not content_tag:
        print("  ❌ No content found", file=sys.stderr)
        return None

    content = content_tag.get_text()
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = content.strip()

    if len(content) < 100:
        print(f"  ❌ Content too short ({len(content)} chars)", file=sys.stderr)
        return None

    print(f"  ✅ Fetched: {title[:50]}... ({len(content)} chars)", file=sys.stderr)

    return {
        "article_id": extract_article_id(url),
        "title": title,
        "author": author,
        "content": content,
        "url": url,
    }


def main():
    parser = argparse.ArgumentParser(description="微信公众号文章抓取工具")
    parser.add_argument("url", help="公众号文章链接")
    args = parser.parse_args()

    result = fetch_article(args.url)
    if not result:
        sys.exit(1)

    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
