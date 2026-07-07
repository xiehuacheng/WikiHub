#!/usr/bin/env python3
"""Export podcast episodes to local markdown source files.

Workflow:
1. Read podcast-export-config.json to know which sources to process.
2. For each configured source, collect episodes via RSS parsing or URL scraping.
3. Skip episodes already recorded in wikihub-exported.json (key: podcast_<episode_id>).
4. Download audio and transcribe remaining episodes using Aliyun FunASR + OSS.
5. Write source markdown to target_wiki (if configured) or Unmapped/.
6. Update wikihub-exported.json and /tmp/wikihub-pending.json.

After this script runs, the standard `make all` pipeline classifies and relocates
the generated source files the same way it handles Cubox articles.
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


def ensure_root():
    if not CONFIG_FILE.exists():
        print("错误：请在 WikiHub/ 项目根目录下运行此脚本", file=sys.stderr)
        sys.exit(1)


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


def collect_episodes(cfg: dict) -> list[dict]:
    """根据 folder 配置收集 episode 列表。"""
    return download_audio.collect_episodes(cfg, root=ROOT)


def print_plan(plan: list):
    total = len(plan)
    print(f"\n{'='*60}")
    print(f"📋 待转录清单（共 {total} 集节目）")
    print(f"{'='*60}")
    for idx, item in enumerate(plan, 1):
        folder = item["folder_name"]
        title = item["title"]
        episode_id = item["episode_id"]
        target = item["rel_path"]
        print(f"  {idx:3d}. [{folder}] {title}")
        print(f"       episode_id: {episode_id} -> {target}")
    print(f"{'='*60}")


def confirm_export(plan: list, auto_confirm: bool = False) -> bool:
    if not plan:
        print("\n没有待转录的节目。")
        return False

    print_plan(plan)

    if auto_confirm:
        print("⏩ 使用 --yes 跳过确认，直接执行导出。\n")
        return True

    if not sys.stdin.isatty():
        print("\n⚠️  检测到非交互环境（无 tty）。")
        print("   如需继续执行导出，请使用 --yes 参数，例如：")
        print("   python3 export-podcast.py --yes")
        return False

    while True:
        answer = input("是否确认执行导出？[y/N] ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", ""):
            return False
        print("请输入 y 或 n")


def parse_args():
    parser = argparse.ArgumentParser(description="导出播客节目并转录为 Markdown")
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过待转录清单确认，直接执行导出",
    )
    parser.add_argument(
        "--urls-file",
        default="",
        help="读取 .urls 文件中的链接进行导出（覆盖配置）",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.urls_file:
        ensure_root()

    if args.urls_file:
        folders_to_process = [{
            "name": "URL列表",
            "source": "urls",
            "urls_file": args.urls_file,
            "target_wiki": "",
            "enabled": True,
        }]
    else:
        if not CONFIG_FILE.exists():
            print(f"❌ 未找到配置文件：{CONFIG_FILE}", file=sys.stderr)
            print("   请先运行 make detect-podcast-folders 初始化配置。", file=sys.stderr)
            sys.exit(1)

        config = load_json(CONFIG_FILE)
        folders_to_process = config.get("folders", [])
        if not folders_to_process:
            print("⚠️  podcast-export-config.json 中没有配置来源。", file=sys.stderr)
            sys.exit(0)

    exported = load_json(EXPORTED_FILE, {})
    now = datetime.now(timezone.utc).isoformat()

    UNMAPPED_DIR.mkdir(exist_ok=True)

    # ---- 收集待导出清单 ----
    plan = []
    skipped = 0
    failed_sources = 0

    for cfg in folders_to_process:
        folder_name = cfg.get("name", "未命名")
        target_wiki = cfg.get("target_wiki", "")

        if cfg.get("enabled") is False:
            print(f"\n📂 跳过来源（已禁用）：{folder_name}")
            continue

        print(f"\n📂 扫描来源：{folder_name}")

        try:
            episodes = collect_episodes(cfg)
        except Exception as e:
            print(f"   ❌ 获取节目列表失败：{e}", file=sys.stderr)
            failed_sources += 1
            continue

        if not episodes:
            print(f"   未找到节目。")
            continue

        target_dir = ROOT / target_wiki if target_wiki else UNMAPPED_DIR

        for idx, ep in enumerate(episodes, 1):
            episode_id = ep.get("episode_id", "")
            if not episode_id:
                print(f"  [{idx}/{len(episodes)}] 无法生成 episode_id，跳过")
                continue

            exported_key = f"podcast_{episode_id}"
            title = ep.get("title", "") or episode_id

            if exported_key in exported:
                print(f"  [{idx}/{len(episodes)}] {title} -> already exported, skipping")
                skipped += 1
                continue

            filename = slugify(title) + ".md"
            file_path = unique_path(target_dir, filename)
            rel_path = str(file_path.relative_to(ROOT))

            plan.append({
                "folder_name": folder_name,
                "target_wiki": target_wiki,
                "episode": ep,
                "episode_id": episode_id,
                "exported_key": exported_key,
                "title": title,
                "target_dir": target_dir,
                "file_path": file_path,
                "rel_path": rel_path,
            })
            print(f"  [{idx}/{len(episodes)}] {title} -> pending")

    # ---- 用户确认 ----
    if not confirm_export(plan, auto_confirm=args.yes):
        print("\n已取消导出。")
        sys.exit(0)

    # ---- 执行导出 ----
    exported_count = 0
    failed = failed_sources
    pending_items = []

    with tempfile.TemporaryDirectory(prefix="podcast-") as tmpdir:
        for item in plan:
            folder_name = item["folder_name"]
            episode = item["episode"]
            episode_id = item["episode_id"]
            exported_key = item["exported_key"]
            title = item["title"]
            target_dir = item["target_dir"]
            file_path = item["file_path"]
            rel_path = item["rel_path"]

            download_url = episode.get("audio_url") or episode.get("url", "")
            if not download_url:
                print(f"\n🎙 转录：{title} ({episode_id})")
                print(f"    -> FAILED: 没有可下载的 URL", file=sys.stderr)
                failed += 1
                continue

            print(f"\n🎙 转录：{title} ({episode_id})")
            try:
                audio_path, _ = download_audio.download_audio(download_url, tmpdir)
            except Exception as e:
                print(f"    -> FAILED to download audio: {e}", file=sys.stderr)
                failed += 1
                continue

            try:
                from asr_client import transcribe_audio
                transcript = transcribe_audio(audio_path, language="auto")
            except Exception as e:
                print(f"    -> FAILED to transcribe: {e}", file=sys.stderr)
                failed += 1
                continue

            target_dir.mkdir(parents=True, exist_ok=True)

            # 更新 episode 元数据：如果下载过程中获得了更准确的标题，以 episode 为准
            frontmatter = build_frontmatter(episode, folder_name, now)
            body = build_body(title, episode.get("url", ""), transcript)

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

            pending_items.append({
                "card_id": exported_key,
                "title": title,
                "url": episode.get("url", ""),
                "path": rel_path,
                "snippet": transcript[:2000],
            })

            exported_count += 1
            print(f"    -> exported to {rel_path}")

    if pending_items:
        save_json(PENDING_FILE, pending_items)
        print(f"\nPending review summary written to {PENDING_FILE} ({len(pending_items)} items).")
    else:
        if PENDING_FILE.exists():
            PENDING_FILE.unlink()

    print("\nDone.")
    print(f"  Exported: {exported_count}")
    print(f"  Skipped (already exported): {skipped}")
    print(f"  Failed: {failed}")


if __name__ == "__main__":
    main()
