#!/usr/bin/env python3
"""Generic podcast episode fetcher.

Supports:
- Apple Podcasts show URL: https://podcasts.apple.com/.../id<show_id>
- Apple Podcasts episode URL: https://podcasts.apple.com/.../id<show_id>?i=<episode_id>
- RSS feed URL: https://.../feed.xml

For each episode it downloads the audio file and writes a Markdown file with
metadata and an audio placeholder. stdout receives a JSON array describing the
result.

Usage:
    python3 fetch.py --url URL --output-dir DIR [--latest N]
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin


NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
AUDIO_EXTS = ("mp3", "m4a", "wav", "ogg", "aac")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audio_hash(url: str) -> str:
    """Stable short hash for audio URLs."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]


def _is_audio_url(url: str) -> bool:
    return bool(re.search(r"\.(" + "|".join(AUDIO_EXTS) + r")(\?|$)", url, re.IGNORECASE))


def _ext_from_url(url: str) -> str:
    url_lower = url.lower().split("?")[0]
    for ext in AUDIO_EXTS:
        if f".{ext}" in url_lower:
            return f".{ext}"
    return ".m4a"


def _curl(url: str, timeout: int = 30, head_only: bool = False) -> subprocess.CompletedProcess:
    cmd = ["curl", "-s", "-L", "--max-time", str(timeout), "-H", f"User-Agent: {USER_AGENT}"]
    if head_only:
        cmd.append("-I")
    cmd.append(url)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)


def _duration_to_seconds(duration) -> int:
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
        return int(parts[-3]) * 3600 + int(parts[-2]) * 60 + int(parts[-1])
    except ValueError:
        return 0


def _title_from_html(html: str, default: str = "") -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return default or "Podcast Episode"
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    title = re.sub(r"\s*[-|—].*$", "", title).strip()
    return title or default or "Podcast Episode"


def _extract_audio_from_html(html: str) -> tuple[str, str]:
    """Extract audio URL and title from HTML.

    Priority:
        1. og:audio meta tag
        2. <audio src>
        3. <audio><source src>
        4. Inline JSON enclosure/url field
        5. Any audio file URL in the page
    """
    title = _title_from_html(html)

    match = re.search(
        r'<meta\s+(?:property|name)=["\']og:audio["\']\s+content=["\'](.*?)["\']',
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(), title

    match = re.search(r'<audio[^>]+src=["\'](.*?)["\']', html, re.IGNORECASE)
    if match:
        return match.group(1).strip(), title

    match = re.search(r'<audio(?:\s[^>]*)?>(.*?)</audio>', html, re.IGNORECASE | re.DOTALL)
    if match:
        source_match = re.search(r'<source[^>]+src=["\'](.*?)["\']', match.group(1), re.IGNORECASE)
        if source_match:
            return source_match.group(1).strip(), title

    match = re.search(
        r'["\'](?:enclosure|url)["\']\s*:\s*["\']'
        r'(https?://[^"\']+\.(?:mp3|m4a|wav|ogg|aac)[^"\']*)["\']',
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(), title

    match = re.search(
        r'(https?://[^\s"\'<>]+\.(?:mp3|m4a|wav|ogg|aac)(?:\?[^\s"\'<>]*)?)',
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(), title

    return "", title


def _resolve_url(base: str, url: str) -> str:
    return urljoin(base, url.strip())


def _decode_filename_from_cd(value: str) -> str:
    match = re.search(r"""filename\*?=["']?(?:UTF-8['"]*)?([^"';\r\n]+)""", value, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        if name.startswith("'"):
            name = name.split("'")[-1]
        try:
            return unquote(name)
        except Exception:
            return name
    return ""


def _safe_title_from_url(url: str) -> str:
    path = url.split("?")[0].split("/")[-1]
    name = Path(path).stem
    return re.sub(r"[\s_]+", " ", name).strip() or "Podcast Episode"


def parse_rss(rss_url: str) -> list[dict]:
    """Parse an RSS feed URL and return a list of episode dicts."""
    result = _curl(rss_url, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch RSS: {result.stderr}")

    root = ET.fromstring(result.stdout)
    items = root.findall(".//item")
    episodes = []

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
    """Scrape a page and extract audio information."""
    result = _curl(url, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch page: {result.stderr}")

    audio_url, title = _extract_audio_from_html(result.stdout)
    if not audio_url:
        raise RuntimeError("Could not extract audio URL from page")

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
    """Download audio to output_dir. Returns (audio_path, metadata)."""
    url = url.strip()
    if not url:
        raise ValueError("URL is empty")

    os.makedirs(output_dir, exist_ok=True)

    if _is_audio_url(url):
        audio_url = url.replace("&amp;", "&")
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
            raise RuntimeError("curl audio download failed (HTTP error 404/403 etc.)")
        raise RuntimeError(f"curl audio download failed, returncode={result.returncode}")

    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    if size_mb < 0.01:
        os.remove(audio_path)
        raise RuntimeError(f"Downloaded file too small ({size_mb:.2f} MB), probably not audio")

    return audio_path, {"title": title, "url": url, "audio_url": audio_url, "duration_seconds": 0}


def is_apple_podcasts_url(url: str) -> bool:
    return "podcasts.apple.com" in url and bool(re.search(r"/id\d+", url))


def parse_apple_podcasts_url(url: str) -> tuple[str | None, str | None]:
    """Parse Apple Podcasts URL into (show_id, episode_id).

    show:     https://podcasts.apple.com/.../id<show_id>
    episode:  https://podcasts.apple.com/.../id<show_id>?i=<episode_id>
    """
    show_match = re.search(r"/id(\d+)", url)
    if not show_match:
        return None, None
    show_id = show_match.group(1)
    ep_match = re.search(r"[?&]i=(\d+)", url)
    episode_id = ep_match.group(1) if ep_match else None
    return show_id, episode_id


def is_rss_url(url: str) -> bool:
    lower = url.lower().rstrip("/")
    if lower.endswith(".xml") or lower.endswith(".rss") or lower.endswith(".feed"):
        return True
    if re.search(r"\.(rss|feed|xml)(\?|$)", lower):
        return True
    if any(k in lower for k in ["/feed", "/rss"]):
        return True
    return False


def identify_url_type(url: str) -> str:
    if is_apple_podcasts_url(url):
        _, episode_id = parse_apple_podcasts_url(url)
        return "apple_show" if episode_id is None else "apple_episode"
    if is_rss_url(url):
        return "rss"
    return "unknown"


def lookup_itunes_feed_url(show_id: str) -> str:
    """Resolve a show_id to its RSS feed URL via the iTunes Search API."""
    api_url = f"https://itunes.apple.com/lookup?id={show_id}&entity=podcast"
    result = _curl(api_url, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"iTunes API request failed: {result.stderr}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"iTunes API returned invalid JSON: {e}")
    results = data.get("results", [])
    if not results:
        raise RuntimeError(f"No podcast found for show_id={show_id}")
    feed_url = results[0].get("feedUrl", "")
    if not feed_url:
        raise RuntimeError("iTunes API did not return feedUrl")
    return feed_url


def fetch_apple_page_title(url: str) -> str:
    """Fetch an Apple Podcasts episode page and return the episode title."""
    result = _curl(url, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch Apple Podcasts page: {result.stderr}")
    html = result.stdout
    title = _title_from_html(html)
    if " - " in title:
        title = title.split(" - ", 1)[0].strip()
    return title


def collect_episodes(url: str, latest: int) -> tuple[list[dict], str]:
    """Collect episodes to fetch for the given URL."""
    url_type = identify_url_type(url)
    info = ""

    if url_type == "apple_show":
        show_id, _ = parse_apple_podcasts_url(url)
        feed_url = lookup_itunes_feed_url(show_id)
        all_eps = parse_rss(feed_url)
        episodes = all_eps[:latest]

    elif url_type == "apple_episode":
        show_id, _ = parse_apple_podcasts_url(url)
        feed_url = lookup_itunes_feed_url(show_id)
        all_eps = parse_rss(feed_url)
        try:
            title = fetch_apple_page_title(url)
            matched = None
            norm_title = title.strip().lower()
            for ep in all_eps:
                if ep.get("title", "").strip().lower() == norm_title:
                    matched = ep
                    break
            if matched:
                episodes = [matched]
            else:
                info = f'Could not match title "{title}" in RSS; falling back to latest episode.'
                episodes = all_eps[:1]
        except Exception as e:
            info = f"Failed to fetch Apple Podcasts page title: {e}; falling back to latest episode."
            episodes = all_eps[:1]

    elif url_type == "rss":
        all_eps = parse_rss(url)
        episodes = all_eps[:latest]

    else:
        raise ValueError(f"Unsupported URL type: {url}")

    return episodes, info


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
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_frontmatter(episode: dict, now: str) -> str:
    title = str(episode.get("title", ""))
    url = episode.get("url", "")
    duration = episode.get("duration", "")
    author = str(episode.get("author", ""))
    lines = [
        "---",
        f'title: "{escape_yaml(title)}"',
        f'url: "{url}"',
        f'author: "{escape_yaml(author)}"',
        f'duration: "{duration}"',
        f'fetched_at: "{now}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def build_markdown(episode: dict, audio_filename: str, now: str) -> str:
    title = episode.get("title", "") or "Podcast Episode"
    url = episode.get("url", "")
    frontmatter = build_frontmatter(episode, now)
    body_lines = [f"# {title}", ""]
    if url:
        body_lines.append(f"[节目链接]({url})")
        body_lines.append("")
    body_lines.append(f"<!-- audio: ./{audio_filename} -->")
    body_lines.append("")
    return frontmatter + "\n".join(body_lines)


def fetch_episode(episode: dict, output_dir: Path, now: str) -> dict:
    title = episode.get("title", "") or episode.get("episode_id", "episode")
    audio_url = episode.get("audio_url") or episode.get("url", "")
    if not audio_url:
        raise ValueError("No audio URL available")

    audio_path, _ = download_audio(audio_url, str(output_dir))
    audio_path_obj = Path(audio_path)

    md_filename = unique_path(output_dir, slugify(title) + ".md")
    md_content = build_markdown(episode, audio_path_obj.name, now)
    md_filename.write_text(md_content, encoding="utf-8")

    return {
        "success": True,
        "file": str(md_filename.resolve()),
        "title": title,
        "url": episode.get("url", ""),
        "author": episode.get("author", ""),
        "media_files": [str(audio_path_obj.resolve())],
        "metadata": {
            "duration": episode.get("duration", ""),
            "episode_id": episode.get("episode_id", ""),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generic podcast episode fetcher")
    parser.add_argument("--url", required=True, help="Apple Podcasts show/episode URL or RSS feed URL")
    parser.add_argument("--output-dir", required=True, help="Directory to write audio and Markdown files")
    parser.add_argument(
        "--latest",
        type=int,
        default=1,
        help="For show/RSS URLs, fetch the latest N episodes (default: 1; ignored for episode URLs)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.latest < 1:
        print("Error: --latest must be >= 1", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        episodes, info = collect_episodes(args.url, args.latest)
    except Exception as e:
        print(f"Failed to collect episodes: {e}", file=sys.stderr)
        sys.exit(1)

    if info:
        print(info, file=sys.stderr)

    if not episodes:
        print("No episodes found.", file=sys.stderr)
        sys.exit(0)

    now = _now_iso()
    results = []
    failed = 0

    for ep in episodes:
        try:
            result = fetch_episode(ep, output_dir, now)
            results.append(result)
        except Exception as e:
            failed += 1
            results.append({
                "success": False,
                "title": ep.get("title", ""),
                "url": ep.get("url", ""),
                "error": str(e),
            })

    print(json.dumps(results, ensure_ascii=False, indent=2))

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
