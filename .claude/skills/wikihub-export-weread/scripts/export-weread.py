#!/usr/bin/env python3
"""
Export WeRead（微信读书）笔记为本地 Markdown source 文件。

流程：
1. 读取 weread-export-config.json。
2. 对每个启用的 folder，拉取有笔记的书籍列表。
3. 跳过 wikihub-exported.json 中已存在的 weread_<bookId>。
4. 确认导出后，拉取每本书的划线与个人想法。
5. 生成 Markdown 文件，更新 wikihub-exported.json 与 /tmp/wikihub-pending.json。

导出后执行 `make all` 可走统一分类、标签与迁移管道。
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weread_api


ROOT = Path.cwd()
CONFIG_FILE = ROOT / "weread-export-config.json"
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
    if not CONFIG_FILE.exists():
        print("错误：请在 WikiHub/ 项目根目录下运行此脚本", file=sys.stderr)
        print("   请先运行 python3 .claude/skills/wikihub-export-weread/scripts/detect-folders.py 初始化配置。", file=sys.stderr)
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


def _coerce_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def parse_notebook(notebook: dict) -> dict:
    """从 /user/notebooks 返回的 notebook 对象中提取统一字段。"""
    book = notebook.get("book") or notebook
    book_id = str(book.get("bookId") or notebook.get("bookId") or "")
    title = _coerce_str(book.get("title") or notebook.get("title")).strip()
    author = _coerce_str(book.get("author") or notebook.get("author")).strip()
    category = _coerce_str(book.get("category") or book.get("categoryName") or notebook.get("category")).strip()
    book_type = _coerce_str(book.get("bookType") or notebook.get("bookType") or "book").strip() or "book"
    return {
        "book_id": book_id,
        "title": title,
        "author": author,
        "category": category,
        "book_type": book_type,
    }


def build_chapter_lookup(chapters: list[dict]) -> dict[str | int, str]:
    lookup = {}
    for ch in chapters:
        uid = ch.get("chapterUid")
        if uid is not None:
            lookup[uid] = ch.get("title", "")
    return lookup


def _range_start(range_str: str) -> int:
    if not range_str:
        return 0
    try:
        return int(str(range_str).split("-")[0])
    except Exception:
        return 0


def build_markdown_body(book_id: str, meta: dict, highlights: list[dict], chapters: list[dict], reviews: list[dict]) -> str:
    title = meta["title"] or "微信读书笔记"
    author = meta["author"]
    url = f"https://weread.qq.com/web/bookDetail/{book_id}"

    lines = [f"# {title}", ""]
    lines.append(f"[微信读书详情]({url})")
    lines.append("")
    if author:
        lines.append(f"> 作者：{author}")
        lines.append("")

    # 章节标题映射
    chapter_lookup = build_chapter_lookup(chapters)

    # 划线按 chapterUid 与 range 排序
    sorted_highlights = sorted(
        highlights,
        key=lambda h: (h.get("chapterUid", 0), _range_start(h.get("range", ""))),
    )

    if sorted_highlights:
        lines.append("## 划线")
        lines.append("")
        current_chapter = None
        for hl in sorted_highlights:
            chapter_uid = hl.get("chapterUid")
            chapter_title = chapter_lookup.get(chapter_uid, "")
            if chapter_title and chapter_title != current_chapter:
                lines.append(f"### {chapter_title}")
                lines.append("")
                current_chapter = chapter_title

            mark_text = str(hl.get("markText") or hl.get("content") or "").strip()
            if not mark_text:
                continue
            create_time = hl.get("createTime", "")
            time_note = f" *({create_time})*" if create_time else ""
            lines.append(f"> {mark_text}{time_note}")
            note = str(hl.get("note") or "").strip()
            if note:
                lines.append("")
                lines.append(f"想法：{note}")
            lines.append("")

    if reviews:
        lines.append("## 我的想法")
        lines.append("")
        for review in reviews:
            content = str(review.get("content") or review.get("review") or "").strip()
            if not content:
                continue
            chapter_uid = review.get("chapterUid")
            chapter_title = chapter_lookup.get(chapter_uid, "")
            create_time = review.get("createTime", "")
            header = []
            if chapter_title:
                header.append(f"章节：{chapter_title}")
            if create_time:
                header.append(f"时间：{create_time}")
            if header:
                lines.append(f"**{' · '.join(header)}**")
            lines.append("")
            lines.append(content)
            lines.append("")

    return "\n".join(lines)


def build_frontmatter(meta: dict, folder_name: str, now: str) -> str:
    tags = ["微信读书"]
    if meta.get("category"):
        tags.append(meta["category"])

    lines = [
        "---",
        f'weread_id: "{meta["book_id"]}"',
        f'title: "{escape_yaml(meta["title"])}"',
        f'url: "https://weread.qq.com/web/bookDetail/{meta["book_id"]}"',
        f'folder: "{escape_yaml(folder_name)}"',
        f'tags: {json.dumps(tags, ensure_ascii=False)}',
        'ai_tags: []',
        f'author: "{escape_yaml(meta["author"])}"',
        f'book_type: "{escape_yaml(meta["book_type"])}"',
        f'exported_at: "{now}"',
        'source: "weread"',
        "---",
        "",
    ]
    return "\n".join(lines)


def collect_books(cfg: dict) -> list[dict]:
    """根据 folder 配置收集书籍元数据列表。"""
    source = cfg.get("source", "notebooks")
    if source == "notebooks":
        notebooks = weread_api.list_notebooks()
        books = []
        seen = set()
        for nb in notebooks:
            meta = parse_notebook(nb)
            book_id = meta["book_id"]
            if not book_id or book_id in seen:
                continue
            seen.add(book_id)
            books.append(meta)
        return books
    return []


def print_plan(plan: list):
    total = len(plan)
    print(f"\n{'='*60}")
    print(f"📋 待导出清单（共 {total} 本书）")
    print(f"{'='*60}")
    for idx, item in enumerate(plan, 1):
        title = item["title_preview"]
        author = item["author"]
        book_id = item["book_id"]
        target = item.get("target_wiki") or "Unmapped/"
        author_hint = f" / {author}" if author else ""
        print(f"  {idx:3d}. {title}{author_hint}")
        print(f"       weread_id: {book_id} -> {target}")
    print(f"{'='*60}")


def confirm_export(plan: list, auto_confirm: bool = False) -> bool:
    if not plan:
        print("\n没有待导出的书籍。")
        return False

    print_plan(plan)

    if auto_confirm:
        print("⏩ 使用 --yes 跳过确认，直接执行导出。\n")
        return True

    if not sys.stdin.isatty():
        print("\n⚠️  检测到非交互环境（无 tty）。")
        print("   如需继续执行导出，请使用 --yes 参数，例如：")
        print("   python3 export-weread.py --yes")
        return False

    while True:
        answer = input("是否确认执行导出？[y/N] ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", ""):
            return False
        print("请输入 y 或 n")


def parse_args():
    parser = argparse.ArgumentParser(description="导出微信读书笔记为 Markdown")
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过待导出清单确认，直接执行导出",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    ensure_root()

    config = load_json(CONFIG_FILE)
    folders_to_process = config.get("folders", [])
    if not folders_to_process:
        print("⚠️  weread-export-config.json 中没有配置 folder。", file=sys.stderr)
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
            print(f"\n📂 跳过 folder（已禁用）：{folder_name}")
            continue

        print(f"\n📂 扫描 folder：{folder_name}")

        try:
            books = collect_books(cfg)
        except Exception as e:
            print(f"   ❌ 获取书籍列表失败：{e}", file=sys.stderr)
            failed_folders += 1
            continue

        if not books:
            print(f"   未找到带笔记的书籍。")
            continue

        target_dir = ROOT / target_wiki if target_wiki else UNMAPPED_DIR

        for idx, meta in enumerate(books, 1):
            book_id = meta["book_id"]
            exported_key = f"weread_{book_id}"
            title_preview = meta["title"] or book_id
            author = meta["author"]

            if exported_key in exported:
                print(f"  [{idx}/{len(books)}] {title_preview} -> already exported, skipping")
                skipped += 1
                continue

            plan.append({
                "folder_name": folder_name,
                "target_wiki": target_wiki,
                "target_dir": target_dir,
                "book_id": book_id,
                "exported_key": exported_key,
                "title_preview": title_preview,
                "author": author,
                "meta": meta,
            })
            print(f"  [{idx}/{len(books)}] {title_preview} -> pending")

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
        book_id = item["book_id"]
        exported_key = item["exported_key"]
        target_dir = item["target_dir"]
        meta = item["meta"]

        print(f"\n📝 导出：{item['title_preview']}")

        try:
            highlights, chapters = weread_api.get_bookmarks(book_id)
            reviews = weread_api.get_reviews(book_id)
        except Exception as e:
            print(f"   ❌ 拉取笔记失败：{e}", file=sys.stderr)
            failed += 1
            continue

        if not highlights and not reviews:
            print("   ⏩ 无划线且无想法，跳过")
            continue

        target_dir.mkdir(parents=True, exist_ok=True)

        filename = slugify(meta["title"] or book_id) + ".md"
        file_path = unique_path(target_dir, filename)
        rel_path = str(file_path.relative_to(ROOT))

        frontmatter = build_frontmatter(meta, folder_name, now)
        body = build_markdown_body(book_id, meta, highlights, chapters, reviews)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + body)

        exported[exported_key] = {
            "title": meta["title"] or book_id,
            "path": rel_path,
            "exported_at": now,
            "source": "weread",
            "folder": folder_name,
        }
        save_json(EXPORTED_FILE, exported)

        snippet = body[:2000]
        pending_items.append({
            "card_id": exported_key,
            "title": meta["title"] or book_id,
            "url": f"https://weread.qq.com/web/bookDetail/{book_id}",
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
