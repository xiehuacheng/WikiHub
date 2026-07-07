#!/usr/bin/env python3
"""单链接导出播客节目。

支持：
- Apple Podcasts show 链接：https://podcasts.apple.com/.../id<show_id>
- Apple Podcasts episode 链接：https://podcasts.apple.com/.../id<show_id>?i=<episode_id>
- RSS feed URL：https://.../xxx.xml

用法：
    python3 export-one.py --url "https://podcasts.apple.com/.../id123456"
    python3 export-one.py --url "https://podcasts.apple.com/.../id123456?i=789"
    python3 export-one.py --url "https://example.com/feed.xml"
    python3 export-one.py --url "https://example.com/feed.xml" --latest 3
"""

import argparse
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd()
CONFIG_FILE = ROOT / "podcast-export-config.json"
EXPORTED_FILE = ROOT / "wikihub-exported.json"
UNMAPPED_DIR = ROOT / "Unmapped"
PENDING_FILE = Path("/tmp/wikihub-pending.json")

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))
import download_audio


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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


def build_frontmatter(episode: dict, folder_name: str, now: str) -> str:
    episode_id = episode.get("episode_id", "")
    title = str(episode.get("title", ""))
    url = episode.get("url", "")
    duration = episode.get("duration", "")
    duration_seconds = episode.get("duration_seconds", 0)
    author = str(episode.get("author", ""))

    lines = [
        "---",
        f'podcast_episode_id: "{episode_id}"',
        f'title: "{escape_yaml(title)}"',
        f'url: "{url}"',
        f'folder: "{escape_yaml(folder_name)}"',
        'source: "podcast"',
        'tags: ["播客"]',
        'ai_tags: []',
        f'author: "{escape_yaml(author)}"',
        f'duration: "{duration}"',
        f'duration_seconds: {duration_seconds}',
        f'exported_at: "{now}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def build_body(title: str, url: str, text: str) -> str:
    lines = [f"# {title}", ""]
    if url:
        lines.append(f"[{url}]({url})")
        lines.append("")
    lines.append(text)
    lines.append("")
    return "\n".join(lines)


def append_pending(pending_item: dict):
    """读取 /tmp/wikihub-pending.json，追加一项后写回。"""
    pending = load_json(PENDING_FILE, [])
    if not isinstance(pending, list):
        pending = []
    pending.append(pending_item)
    save_json(PENDING_FILE, pending)


def detect_target_wiki() -> str:
    """从 podcast-export-config.json 读取第一个 enabled folder 的 target_wiki。

    配置文件不存在、未启用或没有 folder 时给出明确提示，并默认导出到 Unmapped/。
    """
    if not CONFIG_FILE.exists():
        print(f"⚠️  未找到配置文件：{CONFIG_FILE}，将导出到 Unmapped/")
        return ""

    config = load_json(CONFIG_FILE, {})
    folders = config.get("folders", [])
    if not folders:
        print(f"⚠️  {CONFIG_FILE} 中没有配置 folder，将导出到 Unmapped/")
        return ""

    for folder in folders:
        if folder.get("enabled", True):
            return folder.get("target_wiki", "")

    print(f"⚠️  {CONFIG_FILE} 中所有 folder 均已禁用（enabled=false），将导出到 Unmapped/")
    return ""


def identify_url_type(url: str) -> str:
    if download_audio.is_apple_podcasts_url(url):
        _, episode_id = download_audio.parse_apple_podcasts_url(url)
        return "apple_show" if episode_id is None else "apple_episode"
    if download_audio.is_rss_url(url):
        return "rss"
    return "unknown"


def collect_episodes(url: str, latest: int) -> tuple[list[dict], str]:
    """根据 URL 类型收集要导出的 episode 列表，返回 (episodes, info_message)。"""
    url_type = identify_url_type(url)
    info = ""

    if url_type == "apple_show":
        show_id, _ = download_audio.parse_apple_podcasts_url(url)
        feed_url = download_audio.lookup_itunes_feed_url(show_id)
        all_eps = download_audio.parse_rss(feed_url)
        episodes = all_eps[:latest]

    elif url_type == "apple_episode":
        show_id, _ = download_audio.parse_apple_podcasts_url(url)
        feed_url = download_audio.lookup_itunes_feed_url(show_id)
        all_eps = download_audio.parse_rss(feed_url)
        try:
            title = download_audio.fetch_apple_page_title(url)
            matched = None
            norm_title = title.strip().lower()
            for ep in all_eps:
                if ep.get("title", "").strip().lower() == norm_title:
                    matched = ep
                    break
            if matched:
                episodes = [matched]
            else:
                info = f'⚠️  未在 RSS 中匹配到标题 "{title}"，默认导出最新 1 集。'
                episodes = all_eps[:1]
        except Exception as e:
            info = f"⚠️  抓取 Apple Podcasts 页面标题失败：{e}，默认导出最新 1 集。"
            episodes = all_eps[:1]

    elif url_type == "rss":
        all_eps = download_audio.parse_rss(url)
        episodes = all_eps[:latest]

    else:
        raise ValueError(f"不支持的 URL 类型：{url}")

    return episodes, info


def export_episode(episode: dict, target_dir: Path, folder_name: str, now: str, exported: dict) -> tuple[Path, str]:
    """下载、转录并写入单个 episode，返回 (file_path, exported_key)。"""
    episode_id = episode.get("episode_id", "")
    if not episode_id:
        raise ValueError("无法生成 episode_id")

    exported_key = f"podcast_{episode_id}"
    title = episode.get("title", "") or episode_id

    if exported_key in exported:
        raise ValueError(f"已导出，跳过：{exported_key}")

    download_url = episode.get("audio_url") or episode.get("url", "")
    if not download_url:
        raise ValueError("没有可下载的音频 URL")

    with tempfile.TemporaryDirectory(prefix="podcast-one-") as tmpdir:
        audio_path, _ = download_audio.download_audio(download_url, tmpdir)

        from asr_client import transcribe_audio
        transcript = transcribe_audio(audio_path, language="auto")

        filename = slugify(title) + ".md"
        file_path = unique_path(target_dir, filename)
        rel_path = str(file_path.relative_to(ROOT))

        frontmatter = build_frontmatter(episode, folder_name, now)
        body = build_body(title, episode.get("url", ""), transcript)

        target_dir.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + body)

        exported[exported_key] = {
            "title": title,
            "path": rel_path,
            "exported_at": now,
            "source": "podcast",
            "folder": folder_name,
        }
        save_json(EXPORTED_FILE, exported)

        append_pending({
            "card_id": exported_key,
            "title": title,
            "url": episode.get("url", ""),
            "path": rel_path,
            "snippet": transcript[:2000],
        })

        return file_path, exported_key


def parse_args():
    parser = argparse.ArgumentParser(description="单链接导出播客节目")
    parser.add_argument("--url", required=True, help="Apple Podcasts 或 RSS feed URL")
    parser.add_argument(
        "--latest",
        type=int,
        default=1,
        help="show/RSS 链接时导出最新几集（默认 1，episode 链接无效）",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.latest < 1:
        print("错误：--latest 必须 >= 1", file=sys.stderr)
        sys.exit(1)

    target_wiki = detect_target_wiki()
    target_dir = ROOT / target_wiki if target_wiki else UNMAPPED_DIR

    exported = load_json(EXPORTED_FILE, {})
    now = datetime.now(timezone.utc).isoformat()

    try:
        episodes, info = collect_episodes(args.url, args.latest)
    except Exception as e:
        print(f"❌ 获取节目列表失败：{e}", file=sys.stderr)
        sys.exit(1)

    if info:
        print(info)

    if not episodes:
        print("未找到可导出的节目。")
        sys.exit(0)

    folder_name = "单链接导出"
    exported_count = 0
    failed = 0

    for ep in episodes:
        try:
            file_path, exported_key = export_episode(ep, target_dir, folder_name, now, exported)
            print(f"✅ 已导出：{file_path}")
            print(f"   去重键：{exported_key}")
            exported_count += 1
        except Exception as e:
            print(f"❌ 导出失败：{ep.get('title', '')} - {e}", file=sys.stderr)
            failed += 1

    print(f"\n完成。导出：{exported_count}，失败：{failed}")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
