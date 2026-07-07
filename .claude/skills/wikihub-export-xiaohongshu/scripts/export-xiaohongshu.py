#!/usr/bin/env python3
"""
Export Xiaohongshu favorites to local markdown source files.

策略：
1. 用 `xhs favorites --json` 获取收藏列表及笔记元数据（CLI，分页拉取）。
2. 对每条笔记，优先用 `xhs read <note_id>` 获取完整详情；失败则用 favorites 元数据兜底。
3. 如果配置了 .urls 文件，也支持 source=urls 模式。
4. 写入 Markdown 后更新 wikihub-exported.json 和 /tmp/wikihub-pending.json。

After this script runs, the standard `make all` pipeline classifies and relocates
the generated source files the same way it handles Cubox articles and Bilibili videos.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_one
import xhs_cli


ROOT = Path.cwd()
CONFIG_FILE = ROOT / "xiaohongshu-export-config.json"
EXPORTED_FILE = ROOT / "wikihub-exported.json"
UNMAPPED_DIR = ROOT / "Unmapped"
PENDING_FILE = Path("/tmp/wikihub-pending.json")


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_root():
    if not (ROOT / "xiaohongshu-export-config.json").exists():
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


def build_frontmatter(data: dict, folder_name: str, now: str) -> str:
    title = str(data.get("title", ""))
    note_id = data.get("note_id", "")
    url = data.get("url", "")
    author = str(data.get("author", ""))
    note_type = data.get("note_type", "image")
    likes = str(data.get("likes", ""))
    collects = str(data.get("collects", ""))
    comments = str(data.get("comments", ""))
    tags = ["小红书"] + list(data.get("tags", []))

    lines = [
        "---",
        f'xiaohongshu_id: "{note_id}"',
        f'title: "{escape_yaml(title)}"',
        f'url: "{url}"',
        f'folder: "{escape_yaml(folder_name)}"',
        f'tags: {json.dumps(tags, ensure_ascii=False)}',
        'ai_tags: []',
        f'note_type: "{note_type}"',
        f'author: "{escape_yaml(author)}"',
        f'likes: "{likes}"',
        f'collects: "{collects}"',
        f'comments: "{comments}"',
        f'exported_at: "{now}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def build_body(data: dict) -> str:
    title = str(data.get("title", "小红书笔记"))
    desc = str(data.get("desc", ""))
    author = str(data.get("author", ""))
    likes = str(data.get("likes", ""))
    collects = str(data.get("collects", ""))
    comments = str(data.get("comments", ""))
    url = data.get("url", "")
    video_url = data.get("video_url")
    note_type = data.get("note_type", "image")
    images = data.get("images", [])

    stat = f"👍 {likes} · ⭐ {collects} · 💬 {comments}" if (likes or collects or comments) else ""
    lines = [f"# {title}", ""]
    if url:
        lines.append(f"[原文链接]({url})")
        lines.append("")
    if author or stat:
        lines.append(f"> 👤 {author or '未知'} | {stat}")
        lines.append("")
    if desc:
        lines.append(desc)

    if note_type == "video" and video_url:
        lines += ["", "## 视频", "", f"- {video_url}"]

    if images:
        lines += ["", "## 图片", ""]
        for u in images:
            lines.append(f"![]({u})")

    lines.append("")
    return "\n".join(lines)


def read_urls_file(path: Path, favorites_lookup: dict[str, dict] | None = None) -> list[dict]:
    """读取 .urls 文件，每行一个 URL，返回元数据列表。

    如果提供了 favorites_lookup（note_id -> meta），会用其中的元数据补全标题、作者等信息。
    """
    if not path.exists():
        return []
    notes = []
    favorites_lookup = favorites_lookup or {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        note_id = xhs_cli.extract_note_id_from_url(line)
        if note_id and note_id in favorites_lookup:
            meta = favorites_lookup[note_id].copy()
            meta["url"] = line
            notes.append(meta)
        else:
            notes.append({
                "note_id": note_id,
                "display_title": "",
                "type": "unknown",
                "cover": {},
                "user": {},
                "interact_info": {},
                "url": line,
            })
    return notes


def _data_from_favorite_meta(meta: dict) -> dict:
    """把 `xhs favorites` 返回的元数据转换为我们统一的数据格式。"""
    note_id = meta.get("note_id", "")
    title = (meta.get("display_title") or "").strip()
    note_type = "video" if meta.get("type") == "video" else "image"
    cover = meta.get("cover") or {}
    cover_url = cover.get("url", "") if isinstance(cover, dict) else ""
    user = meta.get("user") or {}
    author = (user.get("nickname") or "").strip()
    interact = meta.get("interact_info") or {}
    likes = str(interact.get("liked_count") or "")

    images = [cover_url] if cover_url else []

    return {
        "note_id": note_id,
        "title": title,
        "desc": "",
        "author": author,
        "tags": [],
        "likes": likes,
        "collects": "",
        "comments": "",
        "images": images,
        "video_url": None,
        "note_type": note_type,
        "url": meta.get("url") or f"https://www.xiaohongshu.com/explore/{note_id}",
    }


def collect_notes(cfg: dict) -> list[dict]:
    """根据 folder 配置收集笔记元数据列表。"""
    source = cfg.get("source", "urls")
    if source == "favorites":
        return xhs_cli.list_favorite_notes()
    elif source == "urls":
        urls_file = cfg.get("urls_file", "")
        if not urls_file:
            return []
        # 为 .urls 文件中的链接补充 favorites 元数据（如果存在）
        favorites_lookup = {n.get("note_id", ""): n for n in xhs_cli.list_favorite_notes()}
        return read_urls_file(ROOT / urls_file, favorites_lookup)
    else:
        return []


def fetch_note_with_fallback(note_id: str, url: str, meta: dict) -> dict:
    """尝试获取笔记完整详情，失败则用元数据兜底。"""
    # 1. 尝试 xhs read（CLI）
    cli_data = xhs_cli.read_note(note_id)
    if cli_data and (cli_data.get("desc") or cli_data.get("title")):
        cli_data["note_id"] = note_id
        cli_data["url"] = url
        return cli_data

    # 2. 尝试 HTTP 抓取
    try:
        return fetch_one.fetch_note(url)
    except Exception as e:
        print(f"    ⚠️  HTTP 抓取也失败：{e}", file=sys.stderr)

    # 3. 用 favorites 元数据兜底
    print("    ⏩ 使用 favorites 元数据生成 Markdown", file=sys.stderr)
    return _data_from_favorite_meta(meta)


def print_plan(plan: list):
    total = len(plan)
    print(f"\n{'='*60}")
    print(f"📋 待导出清单（共 {total} 条笔记）")
    print(f"{'='*60}")
    for idx, item in enumerate(plan, 1):
        folder = item["folder_name"]
        title = item["title_preview"]
        note_id = item["note_id"]
        target_wiki = item.get("target_wiki", "")
        target = target_wiki if target_wiki else "Unmapped/"
        print(f"  {idx:3d}. [{folder}] {title}")
        print(f"       note_id: {note_id} -> {target}")
    print(f"{'='*60}")


def confirm_export(plan: list, auto_confirm: bool = False) -> bool:
    if not plan:
        print("\n没有待导出的笔记。")
        return False

    print_plan(plan)

    if auto_confirm:
        print("⏩ 使用 --yes 跳过确认，直接执行导出。\n")
        return True

    if not sys.stdin.isatty():
        print("\n⚠️  检测到非交互环境（无 tty）。")
        print("   如需继续执行导出，请使用 --yes 参数，例如：")
        print("   python3 export-xiaohongshu.py --yes")
        return False

    while True:
        answer = input("是否确认执行导出？[y/N] ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", ""):
            return False
        print("请输入 y 或 n")


def parse_args():
    parser = argparse.ArgumentParser(description="导出小红书收藏夹笔记为 Markdown")
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过待导出清单确认，直接执行导出",
    )
    parser.add_argument(
        "--urls-file",
        default="",
        help="读取 .urls 文件中的笔记链接进行导出（覆盖配置）",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.urls_file:
        ensure_root()

    # 检查 xhs CLI 是否已安装并登录
    try:
        xhs_cli.ensure_ready()
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

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
            print("   请先运行 make detect-xiaohongshu-folders 初始化配置。", file=sys.stderr)
            sys.exit(1)

        config = load_json(CONFIG_FILE)
        folders_to_process = config.get("folders", [])
        if not folders_to_process:
            print("⚠️  xiaohongshu-export-config.json 中没有配置收藏夹。", file=sys.stderr)
            sys.exit(0)

    exported = load_json(EXPORTED_FILE, {})
    now = datetime.now(timezone.utc).isoformat()

    UNMAPPED_DIR.mkdir(exist_ok=True)

    # ---- 收集待导出清单 ----
    plan = []
    skipped = 0
    failed_folders = 0

    for cfg in folders_to_process:
        folder_name = cfg.get("name", "未命名")
        target_wiki = cfg.get("target_wiki", "")

        if cfg.get("enabled") is False:
            print(f"\n📂 跳过收藏夹（已禁用）：{folder_name}")
            continue

        print(f"\n📂 扫描收藏夹：{folder_name}")

        try:
            notes = collect_notes(cfg)
        except Exception as e:
            print(f"   ❌ 获取笔记列表失败：{e}", file=sys.stderr)
            failed_folders += 1
            continue

        if not notes:
            print(f"   未找到笔记。")
            continue

        target_dir = ROOT / target_wiki if target_wiki else UNMAPPED_DIR

        for idx, meta in enumerate(notes, 1):
            note_id = meta.get("note_id", "")
            if not note_id:
                print(f"  [{idx}/{len(notes)}] 无法提取 note_id，跳过")
                continue

            exported_key = f"xhs_{note_id}"
            url = meta.get("url") or f"https://www.xiaohongshu.com/explore/{note_id}"
            title_preview = (meta.get("display_title") or "").strip() or note_id

            if exported_key in exported:
                print(f"  [{idx}/{len(notes)}] {title_preview} -> already exported, skipping")
                skipped += 1
                continue

            plan.append({
                "folder_name": folder_name,
                "target_wiki": target_wiki,
                "url": url,
                "note_id": note_id,
                "exported_key": exported_key,
                "title_preview": title_preview,
                "target_dir": target_dir,
                "meta": meta,
            })
            print(f"  [{idx}/{len(notes)}] {title_preview} -> pending")

    # ---- 用户确认 ----
    if not confirm_export(plan, auto_confirm=args.yes):
        print("\n已取消导出。")
        sys.exit(0)

    # ---- 执行导出 ----
    exported_count = 0
    failed = failed_folders
    pending_items = []

    for item in plan:
        folder_name = item["folder_name"]
        note_id = item["note_id"]
        exported_key = item["exported_key"]
        url = item["url"]
        target_dir = item["target_dir"]
        meta = item["meta"]

        print(f"\n📝 导出：{item['title_preview']}")
        data = fetch_note_with_fallback(note_id, url, meta)

        target_dir.mkdir(parents=True, exist_ok=True)

        title = data.get("title") or item["title_preview"] or "untitled"
        filename = slugify(title) + ".md"
        file_path = unique_path(target_dir, filename)
        rel_path = str(file_path.relative_to(ROOT))

        frontmatter = build_frontmatter(data, folder_name, now)
        body = build_body(data)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + body)

        exported[exported_key] = {
            "title": title,
            "path": rel_path,
            "exported_at": now,
            "source": "xiaohongshu",
            "folder": folder_name,
        }
        save_json(EXPORTED_FILE, exported)

        snippet = (data.get("desc") or item["title_preview"] or "")[:2000]
        pending_items.append({
            "card_id": exported_key,
            "title": title,
            "url": data.get("url", url),
            "path": rel_path,
            "snippet": snippet,
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
