#!/usr/bin/env python3
"""
Export WeChat 公众号文章 to local markdown source files.

策略：
1. 读取 wechat-export-config.json 中的 folder 配置（或 --urls-file 直接指定）。
2. 对每个启用配置，读取 urls_file 中每行一个公众号文章链接。
3. 使用 curl + BeautifulSoup 抓取页面正文。
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
import fetch_article


ROOT = Path.cwd()
CONFIG_FILE = ROOT / "wechat-export-config.json"
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
        print("   请先运行 make detect-wechat-folders 初始化配置。", file=sys.stderr)
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
    """对 YAML 双引号字符串中的特殊字符进行转义。"""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def build_frontmatter(data: dict, folder_name: str, now: str) -> str:
    title = str(data.get("title", ""))
    article_id = str(data.get("article_id", ""))
    url = data.get("url", "")
    author = str(data.get("author", ""))
    tags = ["公众号"]

    lines = [
        "---",
        f'wechat_article_id: "{article_id}"',
        f'title: "{escape_yaml(title)}"',
        f'url: "{url}"',
        f'folder: "{escape_yaml(folder_name)}"',
        f'tags: {json.dumps(tags, ensure_ascii=False)}',
        'ai_tags: []',
        f'author: "{escape_yaml(author)}"',
        f'exported_at: "{now}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def build_body(data: dict) -> str:
    title = str(data.get("title", "公众号文章"))
    author = str(data.get("author", ""))
    url = data.get("url", "")
    content = str(data.get("content", ""))

    lines = [f"# {title}", ""]
    if url:
        lines.append(f"[原文链接]({url})")
        lines.append("")
    if author:
        lines.append(f"> 作者：{author}")
        lines.append("")
    if content:
        lines.append(content)
    lines.append("")
    return "\n".join(lines)


def read_urls_file(path: Path) -> list[str]:
    """读取 .urls 文件，每行一个 URL，返回去重后的 URL 列表。"""
    if not path.exists():
        return []
    urls = []
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            continue
        seen.add(line)
        urls.append(line)
    return urls


def print_plan(plan: list):
    total = len(plan)
    print(f"\n{'='*60}")
    print(f"📋 待导出清单（共 {total} 篇文章）")
    print(f"{'='*60}")
    for idx, item in enumerate(plan, 1):
        folder = item["folder_name"]
        title = item["title_preview"]
        article_id = item["article_id"]
        target_wiki = item.get("target_wiki", "")
        target = target_wiki if target_wiki else "Unmapped/"
        print(f"  {idx:3d}. [{folder}] {title}")
        print(f"       article_id: {article_id} -> {target}")
    print(f"{'='*60}")


def confirm_export(plan: list, auto_confirm: bool = False) -> bool:
    if not plan:
        print("\n没有待导出的文章。")
        return False

    print_plan(plan)

    if auto_confirm:
        print("⏩ 使用 --yes 跳过确认，直接执行导出。\n")
        return True

    if not sys.stdin.isatty():
        print("\n⚠️  检测到非交互环境（无 tty）。")
        print("   如需继续执行导出，请使用 --yes 参数，例如：")
        print("   python3 export-wechat.py --yes")
        return False

    while True:
        answer = input("是否确认执行导出？[y/N] ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", ""):
            return False
        print("请输入 y 或 n")


def parse_args():
    parser = argparse.ArgumentParser(description="导出微信公众号文章为 Markdown")
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过待导出清单确认，直接执行导出",
    )
    parser.add_argument(
        "--urls-file",
        default="",
        help="读取 .urls 文件中的文章链接进行导出（覆盖配置）",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.urls_file:
        folders_to_process = [{
            "name": "URL列表",
            "source": "urls",
            "urls_file": args.urls_file,
            "target_wiki": "",
            "enabled": True,
        }]
    else:
        ensure_root()
        config = load_json(CONFIG_FILE)
        folders_to_process = config.get("folders", [])
        if not folders_to_process:
            print("⚠️  wechat-export-config.json 中没有配置 folder。", file=sys.stderr)
            sys.exit(0)

    exported = load_json(EXPORTED_FILE, {})
    now = datetime.now(timezone.utc).isoformat()

    UNMAPPED_DIR.mkdir(exist_ok=True)

    # ---- 收集待导出清单 ----
    plan = []
    skipped = 0

    for cfg in folders_to_process:
        folder_name = cfg.get("name", "未命名")
        target_wiki = cfg.get("target_wiki", "")

        if cfg.get("enabled") is False:
            print(f"\n📂 跳过 folder（已禁用）：{folder_name}")
            continue

        print(f"\n📂 扫描 folder：{folder_name}")

        urls = read_urls_file(ROOT / cfg.get("urls_file", ""))
        if not urls:
            print(f"   未找到 URL。")
            continue

        target_dir = ROOT / target_wiki if target_wiki else UNMAPPED_DIR

        for idx, url in enumerate(urls, 1):
            article_id = fetch_article.extract_article_id(url)
            if not article_id:
                print(f"  [{idx}/{len(urls)}] 无法提取 article_id，跳过")
                continue

            exported_key = f"wechat_{article_id}"
            title_preview = url

            if exported_key in exported:
                print(f"  [{idx}/{len(urls)}] {title_preview} -> already exported, skipping")
                skipped += 1
                continue

            plan.append({
                "folder_name": folder_name,
                "target_wiki": target_wiki,
                "url": url,
                "article_id": article_id,
                "exported_key": exported_key,
                "title_preview": title_preview,
                "target_dir": target_dir,
            })
            print(f"  [{idx}/{len(urls)}] {title_preview} -> pending")

    # ---- 用户确认 ----
    if not confirm_export(plan, auto_confirm=args.yes):
        print("\n已取消导出。")
        sys.exit(0)

    # ---- 执行导出 ----
    exported_count = 0
    failed = 0
    pending_items = []

    for item in plan:
        folder_name = item["folder_name"]
        article_id = item["article_id"]
        exported_key = item["exported_key"]
        url = item["url"]
        target_dir = item["target_dir"]

        print(f"\n📝 导出：{item['title_preview']}")
        try:
            data = fetch_article.fetch_article(url)
        except RuntimeError as e:
            print(f"   ❌ 抓取失败：{e}", file=sys.stderr)
            failed += 1
            continue
        if not data:
            failed += 1
            continue

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
            "source": "wechat",
            "folder": folder_name,
        }
        save_json(EXPORTED_FILE, exported)

        snippet = (data.get("content") or item["title_preview"] or "")[:2000]
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
