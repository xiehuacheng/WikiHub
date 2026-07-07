#!/usr/bin/env python3
"""
单条小红书笔记导出脚本。

用法：
    python export-one.py --url "https://www.xiaohongshu.com/explore/<note_id>"

行为：
1. 读取项目根目录 xiaohongshu-export-config.json 获取 target_wiki（可选）。
2. 复用 fetch_one.fetch_note / xhs_cli 抓取笔记详情。
3. 生成 Markdown 文件到 target_wiki 或 Unmapped/。
4. 去重键 xhs_<note_id> 写入 wikihub-exported.json。
5. 追加 pending item 到 /tmp/wikihub-pending.json。
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


def determine_target_wiki(config: dict | None) -> str:
    """从配置中查找启用的、指向 urls 的 folder 的 target_wiki；没有则返回空字符串。"""
    if not config:
        return ""
    for folder in config.get("folders", []):
        if folder.get("enabled") is False:
            continue
        target_wiki = folder.get("target_wiki", "")
        if target_wiki:
            return target_wiki
    return ""


def append_pending(item: dict):
    """读取 /tmp/wikihub-pending.json（如存在），追加 item 后写回。"""
    pending = load_json(PENDING_FILE, [])
    if not isinstance(pending, list):
        pending = []
    pending.append(item)
    save_json(PENDING_FILE, pending)


def parse_args():
    parser = argparse.ArgumentParser(description="导出单条小红书笔记为 Markdown")
    parser.add_argument("--url", required=True, help="小红书笔记链接")
    parser.add_argument(
        "--target-wiki",
        default="",
        help="目标 wiki raw 目录（覆盖配置，留空则写入 Unmapped/）",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    url = args.url.strip()

    note_id = xhs_cli.extract_note_id_from_url(url)
    if not note_id:
        print(f"❌ 无法从小红书 URL 提取 note_id：{url}", file=sys.stderr)
        sys.exit(1)

    exported_key = f"xhs_{note_id}"

    # 1. 读取配置（可选）
    config = None
    if CONFIG_FILE.exists():
        config = load_json(CONFIG_FILE)
        if not isinstance(config, dict):
            config = {}
        # 如果全部 enabled=false，给出提示但仍继续
        all_disabled = all(f.get("enabled") is False for f in config.get("folders", []))
        if all_disabled and config.get("folders"):
            print("⚠️  xiaohongshu-export-config.json 中所有收藏夹已禁用，将使用默认目标目录。", file=sys.stderr)
    else:
        print("⚠️  未找到 xiaohongshu-export-config.json，将使用默认目标目录 Unmapped/。", file=sys.stderr)

    # 2. 确定目标目录
    target_wiki = args.target_wiki
    if not target_wiki and config is not None:
        target_wiki = determine_target_wiki(config)
    target_dir = ROOT / target_wiki if target_wiki else UNMAPPED_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    # 3. 检查是否已导出
    exported = load_json(EXPORTED_FILE, {})
    if exported_key in exported:
        print(f"⏩ 笔记已导出：{exported[exported_key]['path']}（{exported_key}）")
        sys.exit(0)

    # 4. 抓取笔记详情
    print(f"📝 导出小红书笔记：{url}")
    try:
        data = fetch_one.fetch_note(url)
    except Exception as e:
        print(f"❌ 抓取失败：{e}", file=sys.stderr)
        sys.exit(1)

    if not data:
        print("❌ 未能获取笔记内容", file=sys.stderr)
        sys.exit(1)

    # 5. 生成 Markdown
    now = datetime.now(timezone.utc).isoformat()
    title = data.get("title") or data.get("desc") or note_id
    filename = slugify(title) + ".md"
    file_path = unique_path(target_dir, filename)
    rel_path = str(file_path.relative_to(ROOT))

    folder_name = "单链接导出"
    frontmatter = build_frontmatter(data, folder_name, now)
    body = build_body(data)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(frontmatter + body)

    # 6. 写入 wikihub-exported.json
    exported[exported_key] = {
        "title": title,
        "path": rel_path,
        "exported_at": now,
        "source": "xiaohongshu",
        "folder": folder_name,
    }
    save_json(EXPORTED_FILE, exported)

    # 7. 追加 pending item
    snippet = (data.get("desc") or title)[:2000]
    append_pending({
        "card_id": exported_key,
        "title": title,
        "url": data.get("url", url),
        "path": rel_path,
        "snippet": snippet,
    })

    print(f"✅ 导出成功：{file_path}")
    print(f"   去重键：{exported_key}")


if __name__ == "__main__":
    main()
