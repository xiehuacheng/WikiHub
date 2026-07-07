#!/usr/bin/env python3
"""
Export Bilibili favorites to local markdown source files.

Workflow:
1. Read bilibili-folder-config.json to know which favorite folders to process.
2. For each configured folder, list videos via `bili favorites <FAV_ID> --yaml`.
3. Skip videos already recorded in wikihub-exported.json.
4. Transcribe remaining videos using bili-collect2md/scripts/transcribe_one_json.py.
5. Write source markdown to target_wiki (if configured) or Unmapped/.
6. Update wikihub-exported.json and /tmp/wikihub-pending.json.

After this script runs, the standard `make all` pipeline classifies and relocates
the generated source files the same way it handles Cubox articles.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd()
CONFIG_FILE = ROOT / "bilibili-export-config.json"
EXPORTED_FILE = ROOT / "wikihub-exported.json"
UNMAPPED_DIR = ROOT / "Unmapped"
PENDING_FILE = Path("/tmp/wikihub-pending.json")
TRANSCRIBE_VENV = ROOT / ".claude" / "skills" / "wikihub-export-bilibili" / ".venv" / "bin" / "python"
TRANSCRIBE_SCRIPT = ROOT / ".claude" / "skills" / "wikihub-export-bilibili" / "scripts" / "transcribe_one_json.py"


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_root():
    if not (ROOT / "bilibili-export-config.json").exists():
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


def run_bili(args: list, timeout: int = 120) -> dict:
    cmd = ["bili"] + args + ["--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(result.stdout)


def extract_list(data, keys=None):
    """从可能是列表或嵌套字典的数据中提取列表。"""
    if data is None:
        return None
    if isinstance(data, list):
        return data
    keys = keys or ["items", "data", "list", "medias"]
    for key in keys:
        if key in data:
            value = data[key]
            if isinstance(value, list):
                return value
            deeper = extract_list(value, keys)
            if deeper:
                return deeper
    return None


def list_favorite_folders() -> list:
    data = run_bili(["favorites"], timeout=60)
    folders = extract_list(data)
    if folders is None:
        raise RuntimeError("无法解析收藏夹列表")
    return folders


def list_videos_in_folder(folder_id: str) -> list:
    data = run_bili(["favorites", folder_id], timeout=120)
    videos = extract_list(data)
    if videos is None:
        raise RuntimeError(f"无法解析收藏夹 {folder_id} 的视频列表")
    return videos


def extract_bvid(text: str) -> str | None:
    """从 URL 或裸 BV 字符串中提取 BVID。"""
    patterns = [
        r"bilibili\.com/video/(BV[\w]+)",
        r"^(BV[\w]+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.strip())
        if match:
            return match.group(1)
    return None


def get_video_info(bvid: str) -> tuple[str, str]:
    """通过 `bili video <bvid> --yaml` 获取视频标题与 UP 主名称。"""
    try:
        cmd = ["bili", "video", bvid, "--yaml"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)
    except Exception as e:
        print(f"   ⚠️  获取视频信息失败（{bvid}）：{e}", file=sys.stderr)
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


def read_urls_file(path: Path) -> list[dict]:
    """读取 .urls 文件，每行一个 URL 或 BV 号，返回视频信息列表。"""
    videos = []
    if not path.exists():
        print(f"   ⚠️  URLs 文件不存在：{path}", file=sys.stderr)
        return videos

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        print(f"   ❌ 读取 URLs 文件失败：{e}", file=sys.stderr)
        return videos

    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        bvid = extract_bvid(text)
        if not bvid:
            print(f"   ⚠️  无法解析 BVID：{text}", file=sys.stderr)
            continue
        title, author = get_video_info(bvid)
        videos.append({
            "bvid": bvid,
            "title": title,
            "upper": {"name": author},
            "duration": "",
            "duration_seconds": 0,
        })
    return videos


def collect_videos(cfg: dict) -> list[dict]:
    """根据配置来源（收藏夹或 URLs 文件）收集视频列表。"""
    source = cfg.get("source", "favorites")
    if source == "favorites":
        return list_videos_in_folder(str(cfg.get("id", "")))
    elif source == "urls":
        urls_file = cfg.get("urls_file", "")
        if not urls_file:
            return []
        return read_urls_file(ROOT / urls_file)
    return []


def escape_yaml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_frontmatter(video: dict, folder_name: str, now: str) -> str:
    bvid = video.get("bvid", video.get("id", ""))
    title = str(video.get("title", ""))
    url = f"https://www.bilibili.com/video/{bvid}/"
    duration = video.get("duration", "")
    duration_seconds = video.get("duration_seconds", 0)
    upper = video.get("upper") or {}
    author = upper.get("name", "") if isinstance(upper, dict) else ""

    lines = [
        "---",
        f'bilibili_bvid: "{bvid}"',
        f'title: "{escape_yaml(title)}"',
        f'url: "{url}"',
        f'folder: "{escape_yaml(folder_name)}"',
        "tags: []",
        "ai_tags: []",
        f'duration: "{duration}"',
        f'duration_seconds: {duration_seconds}',
        f'author: "{escape_yaml(author)}"',
        f'synced_at: "{now}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def transcribe_video(bvid: str, timeout: int = 600) -> dict:
    """调用 bili-collect2md 的转录脚本，返回 {title, uploader, text}。"""
    python = str(TRANSCRIBE_VENV) if TRANSCRIBE_VENV.exists() else "python3"
    cmd = [python, str(TRANSCRIBE_SCRIPT), bvid]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return json.loads(result.stdout)


def build_body(title: str, url: str, text: str) -> str:
    return f"# {title}\n\n[{url}]({url})\n\n{text}\n"


def print_plan(plan: list):
    total = len(plan)
    print(f"\n{'='*60}")
    print(f"📋 待转录清单（共 {total} 个视频）")
    print(f"{'='*60}")

    for idx, item in enumerate(plan, 1):
        folder = item["folder_name"]
        title = item["title"]
        bvid = item["bvid"]
        target = item["rel_path"]
        print(f"  {idx:3d}. [{folder}] {title}")
        print(f"       BVID: {bvid} -> {target}")

    print(f"{'='*60}")


def confirm_transcription(plan: list, auto_confirm: bool = False) -> bool:
    if not plan:
        print("\n没有待转录的视频。")
        return False

    print_plan(plan)

    if auto_confirm:
        print("⏩ 使用 --yes 跳过确认，直接执行转录。\n")
        return True

    if not sys.stdin.isatty():
        print("\n⚠️  检测到非交互环境（无 tty）。")
        print("   如需继续执行转录，请使用 --yes 参数，例如：")
        print("   python3 export-bilibili.py --yes")
        return False

    while True:
        answer = input("是否确认执行转录？[y/N] ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", ""):
            return False
        print("请输入 y 或 n")


def parse_args():
    parser = argparse.ArgumentParser(description="导出 B 站收藏夹视频并转录为 Markdown")
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过待转录清单确认，直接执行转录",
    )
    parser.add_argument(
        "--urls-file",
        default="",
        help="读取 .urls 文件中的 BV 链接进行导出（覆盖配置）",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.urls_file:
        ensure_root()

    if args.urls_file:
        folders_to_process = [{
            "id": "",
            "name": "URL列表",
            "source": "urls",
            "urls_file": args.urls_file,
            "target_wiki": "",
            "enabled": True,
        }]
    else:
        if not CONFIG_FILE.exists():
            print(f"❌ 未找到配置文件：{CONFIG_FILE}", file=sys.stderr)
            print("   请先创建 bilibili-export-config.json 并配置要同步的收藏夹。", file=sys.stderr)
            sys.exit(1)

        config = load_json(CONFIG_FILE)
        folders_to_process = config.get("folders", [])
        if not folders_to_process:
            print("⚠️  bilibili-export-config.json 中没有配置收藏夹。", file=sys.stderr)
            sys.exit(0)

    exported = load_json(EXPORTED_FILE, {})
    now = datetime.now(timezone.utc).isoformat()

    UNMAPPED_DIR.mkdir(exist_ok=True)

    # Optionally validate configured folder ids against actual favorites
    has_favorites = any(cfg.get("source", "favorites") == "favorites" for cfg in folders_to_process)
    if has_favorites:
        all_folders = list_favorite_folders()
        valid_folder_ids = {str(f.get("id", "")) for f in all_folders}
    else:
        valid_folder_ids = set()

    # ---- 收集待转录清单 ----
    plan = []
    skipped = 0
    failed_folders = 0

    for cfg in folders_to_process:
        folder_id = str(cfg.get("id", ""))
        folder_name = cfg.get("name", "未命名")
        target_wiki = cfg.get("target_wiki", "")
        source = cfg.get("source", "favorites")

        if source == "favorites" and not folder_id:
            print(f"⚠️  收藏夹配置缺少 id：{cfg}", file=sys.stderr)
            continue

        if cfg.get("enabled") is False:
            print(f"\n📂 跳过（已禁用）：{folder_name}")
            continue

        if source == "favorites" and folder_id not in valid_folder_ids:
            print(f"⚠️  收藏夹 ID {folder_id}（{folder_name}）不在当前账号的收藏夹列表中，跳过。", file=sys.stderr)
            continue

        print(f"\n📂 扫描：{folder_name}")

        try:
            videos = collect_videos(cfg)
        except Exception as e:
            print(f"   ❌ 获取视频列表失败：{e}", file=sys.stderr)
            failed_folders += 1
            continue

        target_dir = ROOT / target_wiki if target_wiki else UNMAPPED_DIR

        for idx, video in enumerate(videos, 1):
            bvid = video.get("bvid", video.get("id", ""))
            title = video.get("title", "untitled")

            if bvid in exported:
                print(f"  [{idx}/{len(videos)}] {title} -> already exported, skipping")
                skipped += 1
                continue

            filename = slugify(title) + ".md"
            file_path = unique_path(target_dir, filename)
            rel_path = str(file_path.relative_to(ROOT))

            plan.append({
                "folder_name": folder_name,
                "folder_id": folder_id,
                "target_wiki": target_wiki,
                "video": video,
                "bvid": bvid,
                "title": title,
                "target_dir": target_dir,
                "file_path": file_path,
                "rel_path": rel_path,
            })
            print(f"  [{idx}/{len(videos)}] {title} -> pending")

    # ---- 用户确认 ----
    if not confirm_transcription(plan, auto_confirm=args.yes):
        print("\n已取消转录。")
        sys.exit(0)

    # ---- 执行转录 ----
    exported_count = 0
    failed = failed_folders
    pending_items = []

    for item in plan:
        folder_name = item["folder_name"]
        bvid = item["bvid"]
        title = item["title"]
        video = item["video"]
        target_dir = item["target_dir"]
        file_path = item["file_path"]
        rel_path = item["rel_path"]

        print(f"\n🎙 转录：{title} ({bvid})")
        try:
            transcript = transcribe_video(bvid, timeout=600)
        except Exception as e:
            print(f"    -> FAILED to transcribe: {e}", file=sys.stderr)
            failed += 1
            continue

        target_dir.mkdir(parents=True, exist_ok=True)

        frontmatter = build_frontmatter(video, folder_name, now)
        body = build_body(
            transcript.get("title", title),
            f"https://www.bilibili.com/video/{bvid}/",
            transcript.get("text", ""),
        )

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + body)

        exported[bvid] = {
            "title": title,
            "path": rel_path,
            "exported_at": now,
            "source": "bilibili",
            "folder": folder_name,
        }
        save_json(EXPORTED_FILE, exported)

        pending_items.append({
            "card_id": bvid,
            "title": title,
            "url": f"https://www.bilibili.com/video/{bvid}/",
            "path": rel_path,
            "snippet": transcript.get("text", "")[:2000],
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
