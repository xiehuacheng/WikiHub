#!/usr/bin/env python3
"""
通用网页抓取工具。

对任意 HTTP/HTTPS 页面做极简正文提取，输出 Markdown 文件与 stdout JSON。
不感知 WikiHub，不读取/写入任何 WikiHub 状态文件。
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


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


def _extract_title(soup) -> str:
    """从 BeautifulSoup 对象提取标题。"""
    # og:title / twitter:title
    for prop in ("og:title", "twitter:title"):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            return tag["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ""


def _extract_author(soup) -> str:
    """尝试提取作者/站点名。"""
    for prop in ("author", "twitter:creator", "og:site_name"):
        tag = soup.find("meta", attrs={"name": prop}) or soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def _jina_fetch(url: str, timeout: int = 30) -> str:
    """使用 Jina Reader (https://r.jina.ai/<URL>) 获取页面 Markdown。"""
    jina_url = f"https://r.jina.ai/{url}"
    req = urllib.request.Request(
        jina_url,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Jina Reader returned HTTP {resp.status}")
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Jina Reader HTTP error: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Jina Reader request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Jina Reader timed out") from exc


def _extract_title_from_markdown(markdown: str) -> str:
    """从 Markdown 文本第一级标题提取标题。"""
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _is_content_container(tag) -> bool:
    """判断标签是否可能是正文容器。"""
    if tag.name in ("script", "style", "nav", "footer", "header", "aside", "form"):
        return False
    attrs = " ".join(str(v) for v in tag.attrs.values() if isinstance(v, str))
    attrs_lower = attrs.lower()
    # common content markers
    positive = ["article", "main", "content", "post", "entry", "body"]
    negative = ["comment", "sidebar", "widget", "advertisement", "ad-", "recommend"]
    if any(p in attrs_lower or p == tag.name for p in positive):
        return True
    if any(n in attrs_lower for n in negative):
        return False
    return tag.name in ("article", "main")


def _extract_content(soup) -> str:
    """使用简单启发式提取正文。"""
    # Remove non-content elements
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    candidates = []
    # Prefer semantic tags
    for name in ("article", "main"):
        for tag in soup.find_all(name):
            text = tag.get_text(separator="\n", strip=True)
            if len(text) > 200:
                candidates.append((tag, text))

    # Then look for divs with lots of paragraph text
    if not candidates:
        for tag in soup.find_all("div"):
            if not _is_content_container(tag):
                continue
            paragraphs = tag.find_all("p")
            text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20)
            if len(text) > 300:
                candidates.append((tag, text))

    if candidates:
        # Pick the candidate with the longest clean text
        best = max(candidates, key=lambda x: len(x[1]))[1]
    else:
        # Fallback to body text
        body = soup.find("body")
        best = body.get_text(separator="\n", strip=True) if body else ""

    # Clean up
    best = re.sub(r"\n{3,}", "\n\n", best)
    return best.strip()


def _fetch_with_bs4(url: str) -> dict:
    """本地 fallback：curl 拉取 HTML + BeautifulSoup4 提取正文。"""
    html = _curl(url)
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("Need beautifulsoup4: pip install beautifulsoup4") from exc

    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup)
    author = _extract_author(soup)
    content = _extract_content(soup)

    if len(content) < 100:
        raise RuntimeError(f"提取正文过短（{len(content)} 字符），可能页面结构不适合")

    parsed = urlparse(url)
    return {
        "title": title,
        "author": author,
        "content": content,
        "domain": parsed.netloc.lower(),
    }


def fetch_page(url: str) -> dict:
    """抓取页面并返回标准数据字典。优先 Jina Reader，失败/超时时回退到本地 bs4。"""
    parsed = urlparse(url)
    page_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]

    # Primary: Jina Reader
    try:
        markdown = _jina_fetch(url)
        title = _extract_title_from_markdown(markdown)
        return {
            "page_id": page_id,
            "title": title,
            "author": "",
            "content": markdown,
            "url": url,
            "domain": parsed.netloc.lower(),
        }
    except Exception as jina_err:
        # Fallback: local curl + bs4
        try:
            data = _fetch_with_bs4(url)
        except Exception as fallback_err:
            raise RuntimeError(
                f"Jina Reader failed ({jina_err}); fallback also failed ({fallback_err})"
            ) from fallback_err
        return {
            "page_id": page_id,
            "title": data["title"],
            "author": data["author"],
            "content": data["content"],
            "url": url,
            "domain": data["domain"],
        }


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


def escape_yaml(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def build_markdown(data: dict, now: str) -> str:
    title = str(data.get("title", "") or "网页文章")
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
        lines.append(f"> 来源：{author}")
        lines.append("")
    if content:
        lines.append(content)
    lines.append("")
    body = "\n".join(lines)
    return frontmatter + body


def main():
    parser = argparse.ArgumentParser(description="通用网页抓取工具")
    parser.add_argument("--url", required=True, help="网页链接")
    parser.add_argument("--output-dir", required=True, help="输出 Markdown 文件的目录")
    args = parser.parse_args()

    url = (args.url or "").strip()
    output_dir = Path(args.output_dir)

    if not url:
        print(json.dumps({"success": False, "error": "--url 不能为空"}, ensure_ascii=False))
        sys.exit(1)

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        data = fetch_page(url)
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    title = data.get("title") or data.get("page_id") or "untitled"
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
            "page_id": data.get("page_id", ""),
            "domain": data.get("domain", ""),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
