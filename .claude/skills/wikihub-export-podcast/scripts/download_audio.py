#!/usr/bin/env python3
"""播客音频下载与 RSS 解析工具。

支持：
- RSS 订阅解析（自动提取 enclosure、itunes:duration、itunes:episode）
- 单条 URL 抓取（自动提取 og:audio、<audio> 标签或内联 JSON 中的音频直链）
- 直链音频下载（.mp3 / .m4a / .wav / .ogg / .aac）

用法（模块）：
    from download_audio import collect_episodes, download_audio
    episodes = collect_episodes({"source": "rss", "urls_file": "podcast-feeds.urls"})
    audio_path, meta = download_audio(episode["audio_url"], "/tmp/output")
"""

import hashlib
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urljoin


NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
AUDIO_EXTS = ("mp3", "m4a", "wav", "ogg", "aac")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _audio_hash(url: str) -> str:
    """生成音频 URL 的短哈希，用于稳定 episode_id。"""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]


def _is_audio_url(url: str) -> bool:
    """判断 URL 是否为直链音频。"""
    return bool(re.search(r"\.(" + "|".join(AUDIO_EXTS) + r")(\?|$)", url, re.IGNORECASE))


def _ext_from_url(url: str) -> str:
    """从 URL 推断音频扩展名。"""
    url_lower = url.lower().split("?")[0]
    for ext in AUDIO_EXTS:
        if f".{ext}" in url_lower:
            return f".{ext}"
    return ".m4a"


def _curl(url: str, timeout: int = 30, head_only: bool = False) -> subprocess.CompletedProcess:
    """使用 curl 抓取 URL。"""
    cmd = ["curl", "-s", "-L", "--max-time", str(timeout),
           "-H", f"User-Agent: {USER_AGENT}"]
    if head_only:
        cmd.append("-I")
    cmd.append(url)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)


def _duration_to_seconds(duration) -> int:
    """把 HH:MM:SS 或 MM:SS 时长转换为秒。"""
    if duration is None:
        return 0
    text = str(duration).strip()
    if not text:
        return 0
    parts = [p.strip() for p in text.split(":") if p.strip()]
    if not parts:
        return 0
    try:
        if len(parts) == 1:
            return int(float(parts[0]))
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        # 超过 3 段只取后三段
        return int(parts[-3]) * 3600 + int(parts[-2]) * 60 + int(parts[-1])
    except ValueError:
        return 0


def _title_from_html(html: str, default: str = "") -> str:
    """从 HTML 中提取标题。"""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return default or "Podcast Episode"
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    # 去掉站点后缀
    title = re.sub(r"\s*[-|—].*$", "", title).strip()
    return title or default or "Podcast Episode"


def _extract_audio_from_html(html: str) -> tuple[str, str]:
    """从 HTML 中提取音频 URL 和标题。

    优先级：
        1. og:audio meta 标签
        2. <audio src>
        3. 内联 JSON audioUrl/mediaSrc/enclosure/url
        4. 页面中任意音频直链
    """
    title = _title_from_html(html)

    # 1. og:audio
    match = re.search(
        r'<meta\s+(?:property|name)=["\']og:audio["\']\s+content=["\'](.*?)["\']',
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(), title

    # 2. <audio src>
    match = re.search(r'<audio[^>]+src=["\'](.*?)["\']', html, re.IGNORECASE)
    if match:
        return match.group(1).strip(), title

    # 2b. <audio><source src="...">
    match = re.search(r'<audio(?:\s[^>]*)?>(.*?)</audio>', html, re.IGNORECASE | re.DOTALL)
    if match:
        source_match = re.search(r'<source[^>]+src=["\'](.*?)["\']', match.group(1), re.IGNORECASE)
        if source_match:
            return source_match.group(1).strip(), title

    # 3. 内联 JSON audioUrl / mediaSrc / enclosure / url
    match = re.search(
        r'["\'](?:audioUrl|mediaSrc|enclosure|url)["\']\s*:\s*["\']'
        r'(https?://[^"\']+\.(?:mp3|m4a|wav|ogg|aac)[^"\']*)["\']',
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(), title

    # 4. 页面中任意音频 URL
    match = re.search(
        r'(https?://[^\s"\'<>]+\.(?:mp3|m4a|wav|ogg|aac)(?:\?[^\s"\'<>]*)?)',
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(), title

    return "", title


def _resolve_url(base: str, url: str) -> str:
    """使用 urllib.parse.urljoin 正确合并相对 URL。"""
    return urljoin(base, url.strip())


def _decode_filename_from_cd(value: str) -> str:
    """从 Content-Disposition 头解析文件名。"""
    # 处理 filename*=UTF-8''xxx 或 filename="xxx"
    match = re.search(r"""filename\*?=["']?(?:UTF-8['"]*)?([^"';\r\n]+)""", value, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        if name.startswith("'"):
            # filename*=UTF-8''name
            name = name.split("'")[-1]
        try:
            return unquote(name)
        except Exception:
            return name
    return ""


def _safe_title_from_url(url: str) -> str:
    """从 URL 路径中提取基础文件名作为标题。"""
    path = url.split("?")[0].split("/")[-1]
    name = Path(path).stem
    return re.sub(r"[\s_]+", " ", name).strip() or "Podcast Episode"


def parse_rss(rss_url: str) -> list[dict]:
    """解析 RSS URL，返回 episode 列表。"""
    result = _curl(rss_url, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"下载 RSS 失败：{result.stderr}")

    root = ET.fromstring(result.stdout)
    items = root.findall(".//item")
    episodes = []

    # 频道级作者兜底
    channel_author = ""
    channel = root.find(".//channel")
    if channel is not None:
        author_el = channel.find("itunes:author", NS)
        if author_el is not None and author_el.text:
            channel_author = author_el.text.strip()

    for idx, item in enumerate(items):
        title_el = item.find("title")
        title = (title_el.text or "").strip() if title_el is not None else ""

        link_el = item.find("link")
        link = (link_el.text or "").strip() if link_el is not None else ""

        enclosure = item.find("enclosure")
        audio_url = ""
        if enclosure is not None:
            audio_url = (enclosure.get("url") or "").strip()
        if not audio_url:
            # 兼容 media:content
            media = item.find("media:content", {"media": "http://search.yahoo.com/mrss/"})
            if media is not None:
                audio_url = (media.get("url") or "").strip()

        if not audio_url:
            continue

        audio_url = audio_url.replace("&amp;", "&")

        duration_el = item.find("itunes:duration", NS)
        duration = (duration_el.text or "").strip() if duration_el is not None else ""

        ep_num_el = item.find("itunes:episode", NS)
        ep_num = (ep_num_el.text or "").strip() if ep_num_el is not None else ""
        if not ep_num:
            # 从标题尝试解析 EPxx / #xx
            m = re.search(r"(?:EP|ep|E|#)\s*(\d+)", title)
            if m:
                ep_num = m.group(1)
        if not ep_num:
            ep_num = str(idx + 1)

        author_el = item.find("itunes:author", NS)
        author = (author_el.text or "").strip() if author_el is not None else ""
        if not author:
            author = channel_author

        episode_id = f"rss_{ep_num}_{_audio_hash(audio_url)}"

        episodes.append({
            "episode_id": episode_id,
            "title": title,
            "url": link or rss_url,
            "audio_url": audio_url,
            "duration": duration,
            "duration_seconds": _duration_to_seconds(duration),
            "author": author,
            "source": "rss",
        })

    return episodes


def extract_audio_from_page(url: str) -> dict:
    """抓取页面并提取音频信息，返回 episode 字典。"""
    result = _curl(url, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"抓取页面失败：{result.stderr}")

    audio_url, title = _extract_audio_from_html(result.stdout)
    if not audio_url:
        raise RuntimeError("无法从页面提取音频 URL")

    audio_url = _resolve_url(url, audio_url)
    audio_url = audio_url.replace("&amp;", "&")
    episode_id = f"url_{_audio_hash(audio_url)}"

    return {
        "episode_id": episode_id,
        "title": title,
        "url": url,
        "audio_url": audio_url,
        "duration": "",
        "duration_seconds": 0,
        "author": "",
        "source": "urls",
    }


def download_audio(url: str, output_dir: str) -> tuple[str, dict]:
    """下载音频到本地，返回 (audio_path, metadata)。

    支持直链音频和页面 URL。
    """
    url = url.strip()
    if not url:
        raise ValueError("URL 为空")

    os.makedirs(output_dir, exist_ok=True)

    if _is_audio_url(url):
        audio_url = url.replace("&amp;", "&")
        # 尝试从 HEAD 响应的 Content-Disposition 获取标题
        title = _safe_title_from_url(url)
        try:
            head = _curl(url, timeout=15, head_only=True)
            if head.returncode == 0:
                for line in head.stdout.splitlines():
                    if line.lower().startswith("content-disposition"):
                        cd_title = _decode_filename_from_cd(line)
                        if cd_title:
                            title = Path(cd_title).stem
                            break
        except Exception:
            pass
    else:
        meta = extract_audio_from_page(url)
        audio_url = meta["audio_url"]
        title = meta["title"]

    ext = _ext_from_url(audio_url)
    safe_title = re.sub(r'[\\/:*?"<>|\s\x00-\x1f]+', "-", title).strip("-")
    if not safe_title:
        safe_title = "episode"

    audio_path = os.path.join(output_dir, f"{safe_title}{ext}")
    counter = 1
    while os.path.exists(audio_path):
        audio_path = os.path.join(output_dir, f"{safe_title}-{counter}{ext}")
        counter += 1

    # 下载音频
    result = subprocess.run(
        [
            "curl", "-L", "-f", "-o", audio_path, "--max-time", "1800", "-s",
            "-H", f"User-Agent: {USER_AGENT}",
            audio_url,
        ],
        timeout=1900,
    )
    if result.returncode != 0:
        if os.path.exists(audio_path):
            os.remove(audio_path)
        if result.returncode == 22:
            raise RuntimeError("curl 下载音频失败，HTTP 错误（404/403 等）")
        raise RuntimeError(f"curl 下载音频失败，returncode={result.returncode}")

    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    if size_mb < 0.01:
        os.remove(audio_path)
        raise RuntimeError(f"下载文件过小（{size_mb:.2f} MB），可能不是音频文件")

    metadata = {
        "title": title,
        "url": url,
        "audio_url": audio_url,
        "duration_seconds": 0,
    }
    return audio_path, metadata


def _read_urls_file(path: Path) -> list[str]:
    """读取 .urls 文件，返回非空 URL 列表。"""
    if not path.exists():
        return []
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def collect_episodes(cfg: dict, root: Path | None = None) -> list[dict]:
    """根据 folder 配置收集 episode 列表。"""
    source = cfg.get("source", "urls")
    urls_file = cfg.get("urls_file", "")
    root = root or Path.cwd()

    if not urls_file:
        return []

    urls = _read_urls_file(root / urls_file)
    if not urls:
        return []

    episodes = []
    if source == "rss":
        for rss_url in urls:
            try:
                eps = parse_rss(rss_url)
                episodes.extend(eps)
            except Exception as e:
                print(f"   ⚠️  解析 RSS 失败（{rss_url}）：{e}")
    elif source == "urls":
        for url in urls:
            try:
                ep = extract_audio_from_page(url)
                episodes.append(ep)
            except Exception as e:
                print(f"   ⚠️  提取音频失败（{url}）：{e}")
    else:
        print(f"   ⚠️  未知的 source 类型：{source}")

    return episodes
