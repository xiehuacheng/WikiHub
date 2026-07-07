#!/usr/bin/env python3
"""
Bilibili video fetcher.

A generic, WikiHub-agnostic utility that downloads the audio of a Bilibili video
and writes a Markdown file with metadata and an audio placeholder.

Usage:
    python3 fetch.py --url "https://www.bilibili.com/video/BVxxx" --output-dir ./out
    python3 fetch.py --url "https://b23.tv/xxxx" --output-dir ./out

Stdout:
    JSON result object.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def log(message: str) -> None:
    """Print progress to stderr so stdout stays clean for JSON output."""
    print(message, file=sys.stderr)


def slugify(text: str, max_bytes: int = 200) -> str:
    """Convert a string into a filesystem-safe slug."""
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
    """Return a non-conflicting path inside directory."""
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


def resolve_b23_url(url: str) -> str:
    """Resolve a b23.tv short URL to its final bilibili.com destination."""
    if "b23.tv" not in url:
        return url

    headers = {"User-Agent": USER_AGENT}
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as resp:
                resolved = resp.geturl()
                if "bilibili.com" in resolved:
                    return resolved
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code == 405:
                continue
            raise RuntimeError(f"无法解析 b23.tv 短链接：{url}，{e}")
        except Exception as e:
            raise RuntimeError(f"无法解析 b23.tv 短链接：{url}，{e}")

    raise RuntimeError(f"无法从 b23.tv 短链接获取 bilibili.com 地址：{url}")


def extract_bvid(text: str) -> str | None:
    """Extract a BVID from a bilibili.com URL or a bare BV string."""
    patterns = [
        r"bilibili\.com/video/(BV[\w]+)",
        r"^(BV[\w]+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.strip())
        if match:
            return match.group(1)
    return None


def parse_url(url: str) -> str:
    """Return the BVID for a bilibili.com or b23.tv URL."""
    if "b23.tv" in url:
        url = resolve_b23_url(url)
    bvid = extract_bvid(url)
    if not bvid:
        raise ValueError(f"无法从 URL 中提取 BVID：{url}")
    return bvid


def escape_frontmatter(value: str) -> str:
    """Escape double quotes inside a YAML double-quoted scalar."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def get_video_info(bvid: str) -> tuple[str, str]:
    """Fetch video title and uploader name via `bili video <bvid> --yaml`."""
    try:
        cmd = ["bili", "video", bvid, "--yaml"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)
    except Exception as e:
        log(f"⚠️  获取视频信息失败（{bvid}）：{e}")
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


def download_audio(bvid: str, output_dir: Path) -> Path:
    """Download the audio track of a Bilibili video using bilibili-cli.

    The audio file is placed directly inside output_dir and renamed to a safe
    filename based on the video title. Returns the final audio path.
    """
    title, author = get_video_info(bvid)
    log(f"📺 {title} | UP: {author or '未知'}")

    safe_title = slugify(title)
    tmp_audio_dir = output_dir / ".bilibili-fetcher-tmp"
    tmp_audio_dir.mkdir(parents=True, exist_ok=True)

    log("⬇️  下载音频...")
    try:
        subprocess.run(
            ["bili", "audio", bvid, "--no-split", "-o", str(tmp_audio_dir)],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"bilibili-cli 下载音频失败：{e.stderr or e.stdout}") from e

    audio_exts = (".m4a", ".mp3", ".aac", ".wav", ".flac", ".ogg")
    files = []
    for ext in audio_exts:
        files.extend(tmp_audio_dir.rglob(f"*{ext}"))

    if not files:
        raise FileNotFoundError(f"未在 {tmp_audio_dir} 找到下载的音频文件")

    source_path = max(files, key=lambda p: p.stat().st_size)
    suffix = source_path.suffix
    target_name = f"{safe_title}{suffix}"
    target_path = unique_path(output_dir, target_name)

    source_path.rename(target_path)
    size_mb = target_path.stat().st_size / (1024 * 1024)
    log(f"✅ 音频已保存：{target_path} ({size_mb:.1f} MB)")

    # Clean up temporary download directory.
    for child in tmp_audio_dir.iterdir():
        if child.is_dir():
            _rmtree(child)
        else:
            child.unlink()
    tmp_audio_dir.rmdir()

    return target_path


def _rmtree(path: Path) -> None:
    """Recursively remove a directory tree."""
    for child in path.iterdir():
        if child.is_dir():
            _rmtree(child)
        else:
            child.unlink()
    path.rmdir()


def build_markdown(title: str, author: str, url: str, audio_filename: str, fetched_at: str) -> str:
    """Build the Markdown content with generic frontmatter."""
    return f"""---
title: "{escape_frontmatter(title)}"
url: "{url}"
author: "{escape_frontmatter(author)}"
fetched_at: "{fetched_at}"
---

# {title}

[视频链接]({url})

<!-- audio: ./{audio_filename} -->
"""


def fetch(url: str, output_dir: Path) -> dict:
    """Fetch a Bilibili video and produce a Markdown file plus audio download.

    Returns a result dictionary compatible with generic fetcher workflows.
    """
    bvid = parse_url(url)
    log(f"🔗 解析到 BVID：{bvid}")

    page_url = f"https://www.bilibili.com/video/{bvid}/"
    title, author = get_video_info(bvid)

    output_dir.mkdir(parents=True, exist_ok=True)

    audio_path = download_audio(bvid, output_dir)
    audio_filename = audio_path.name

    fetched_at = datetime.now(timezone.utc).isoformat()
    markdown = build_markdown(title, author, page_url, audio_filename, fetched_at)

    md_filename = slugify(title) + ".md"
    md_path = unique_path(output_dir, md_filename)
    md_path.write_text(markdown, encoding="utf-8")
    log(f"✅ Markdown 已保存：{md_path}")

    return {
        "success": True,
        "file": str(md_path),
        "title": title,
        "url": page_url,
        "author": author,
        "media_files": [str(audio_path)],
        "metadata": {"bvid": bvid},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="下载 B 站视频音频并生成 Markdown 元数据文件（通用工具，不依赖 WikiHub）"
    )
    parser.add_argument("--url", required=True, help="B 站视频链接，支持 bilibili.com 和 b23.tv")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()

    try:
        result = fetch(args.url, output_dir)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        log(f"❌ 获取失败：{e}")
        result = {
            "success": False,
            "error": str(e),
            "url": args.url,
            "file": None,
            "title": None,
            "author": None,
            "media_files": [],
            "metadata": {},
        }
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
