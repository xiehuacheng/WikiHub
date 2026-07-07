#!/usr/bin/env python3
"""
Apply tags from wikihub-tags.json to:
- wikihub-exported.json records
- each markdown file's frontmatter
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path.cwd()
TAGS_FILE = ROOT / "wikihub-tags.json"
EXPORTED_FILE = ROOT / "wikihub-exported.json"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_frontmatter_tags(file_path: Path, tags: list[str]):
    text = file_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False

    parts = text.split("---", 2)
    if len(parts) < 3:
        return False

    fm = parts[1]
    body = parts[2]

    # Check if ai_tags already exists
    if re.search(r"^ai_tags:\s*", fm, re.MULTILINE):
        # Replace existing ai_tags line
        fm = re.sub(
            r"^ai_tags:.*$",
            f"ai_tags: {json.dumps(tags, ensure_ascii=False)}",
            fm,
            flags=re.MULTILINE,
        )
    else:
        # Add ai_tags after tags line or at end of frontmatter
        lines = fm.rstrip().split("\n")
        tags_idx = -1
        for i, line in enumerate(lines):
            if line.startswith("tags:"):
                tags_idx = i
                break
        ai_tags_line = f"ai_tags: {json.dumps(tags, ensure_ascii=False)}"
        if tags_idx >= 0:
            lines.insert(tags_idx + 1, ai_tags_line)
        else:
            lines.append(ai_tags_line)
        fm = "\n".join(lines)

    body = body.lstrip("\n")
    new_text = f"---{fm}---\n\n{body}"
    file_path.write_text(new_text, encoding="utf-8")
    return True


_EXPORT_CONFIG_FILES = [
    "wikihub-orchestrator-config.json",
    "bilibili-export-config.json",
    "cubox-export-config.json",
    "xiaohongshu-export-config.json",
    "weread-export-config.json",
    "wechat-export-config.json",
    "podcast-export-config.json",
]


def ensure_root():
    if not any((ROOT / name).exists() for name in _EXPORT_CONFIG_FILES):
        print("错误：请在 WikiHub/ 项目根目录下运行此脚本", file=sys.stderr)
        sys.exit(1)


def main():
    ensure_root()
    tags = load_json(TAGS_FILE)
    exported = load_json(EXPORTED_FILE)

    updated_exported = 0
    updated_files = 0
    failed_files = []

    for card_id, tag_list in tags.items():
        if card_id not in exported:
            continue

        # Update exported record
        exported[card_id]["ai_tags"] = tag_list
        updated_exported += 1

        # Update markdown file
        file_path = ROOT / exported[card_id]["path"]
        if file_path.exists():
            if update_frontmatter_tags(file_path, tag_list):
                updated_files += 1
            else:
                failed_files.append(str(file_path))
        else:
            failed_files.append(str(file_path))

    save_json(EXPORTED_FILE, exported)

    print(f"Updated exported records: {updated_exported}")
    print(f"Updated markdown files: {updated_files}")
    if failed_files:
        print(f"Failed: {len(failed_files)}")
        for f in failed_files[:10]:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
