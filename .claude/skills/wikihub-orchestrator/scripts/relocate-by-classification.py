#!/usr/bin/env python3
"""
Relocate exported Cubox markdown files based on AI content tags.

This script no longer reads /tmp/classification.json. Instead, it derives
target directories from the ai_tags field in wikihub-exported.json using a
TAG_TO_DIR mapping. Files already in Quarantine/ are left untouched.
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path.cwd()
EXPORTED_FILE = ROOT / "wikihub-exported.json"
TAG_CONFIG_FILE = ROOT / "wikihub-tag-config.json"


def load_tag_config() -> dict:
    """加载标签映射配置。"""
    if not TAG_CONFIG_FILE.exists():
        print(f"错误：未找到标签配置文件 {TAG_CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(TAG_CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


TAG_TO_DIR = load_tag_config().get("tag_to_dir", {})


_ROOT_MARKERS = [
    ".claude/skills/wikihub-orchestrator/wikihub-orchestrator-config.json",
    "wikihub-orchestrator-config.json",
    "Makefile",
]


def ensure_root():
    if not any((ROOT / name).exists() for name in _ROOT_MARKERS):
        print("错误：请在 WikiHub/ 项目根目录下运行此脚本", file=sys.stderr)
        sys.exit(1)


def derive_target_dir(ai_tags: list[str]) -> str | None:
    for tag in ai_tags:
        if tag in TAG_TO_DIR:
            return TAG_TO_DIR[tag]
    return None


def move_with_assets(src: Path, dst: Path):
    """移动 Markdown 文件时，同步移动同名的 .assets/ 目录（如果存在）。"""
    shutil.move(str(src), str(dst))
    src_assets = src.parent / f"{src.stem}.assets"
    if src_assets.exists():
        dst_assets = dst.parent / f"{dst.stem}.assets"
        counter = 1
        original_dst_assets = dst_assets
        while dst_assets.exists():
            dst_assets = dst_assets.parent / f"{original_dst_assets.stem}-{counter}{original_dst_assets.suffix}"
            counter += 1
        shutil.move(str(src_assets), str(dst_assets))


def main():
    ensure_root()
    with open(EXPORTED_FILE, "r", encoding="utf-8") as f:
        exported = json.load(f)

    moved = 0
    skipped = 0
    failed = 0

    for card_id, record in exported.items():
        path = Path(record["path"])

        # Only relocate files currently in Unmapped/
        if path.parts[0] != "Unmapped":
            continue

        src = ROOT / path
        if not src.exists():
            print(f"Source not found: {src}")
            skipped += 1
            continue

        ai_tags = record.get("ai_tags", [])
        target_dir_str = derive_target_dir(ai_tags)

        if not target_dir_str:
            # No known wiki for these tags; keep in Unmapped
            continue

        target_dir = ROOT / target_dir_str
        target_dir.mkdir(parents=True, exist_ok=True)

        dst = target_dir / src.name
        if dst.exists():
            print(f"Destination exists, skipping: {dst}")
            skipped += 1
            continue

        try:
            move_with_assets(src, dst)
            rel_path = str(dst.relative_to(ROOT))
            record["path"] = rel_path
            print(f"Moved: {src.name} -> {rel_path}")
            moved += 1
        except Exception as e:
            print(f"Failed to move {src.name}: {e}")
            failed += 1

    with open(EXPORTED_FILE, "w", encoding="utf-8") as f:
        json.dump(exported, f, ensure_ascii=False, indent=2)

    remaining = len(list((ROOT / "Unmapped").glob("*.md")))

    print("\nDone.")
    print(f"  Moved: {moved}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed: {failed}")
    print(f"  Remaining in Unmapped: {remaining}")


if __name__ == "__main__":
    main()
