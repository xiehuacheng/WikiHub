#!/usr/bin/env python3
"""
Export Cubox cards to local markdown files organized by wiki.

Mapping rules:
- cubox-export-config.json maps Cubox folder names to target wiki raw directories.
- Cards whose Cubox folder has no mapping go to ./Unmapped/.
- wikihub-exported.json tracks exported cards to avoid duplicates.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path.cwd()
MAPPING_FILE = ROOT / "cubox-export-config.json"
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


def run_cubox(args: list[str]) -> dict | list:
    cmd = ["cubox-cli"] + args + ["-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def slugify(text: str, max_bytes: int = 200) -> str:
    if not text:
        text = "untitled"
    # Remove characters that are illegal in filenames
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    # Replace whitespace and control chars with single hyphen
    text = re.sub(r"[\s\x00-\x1f]+", "-", text)
    # Collapse multiple hyphens
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    if not text:
        text = "untitled"
    # Limit byte length to avoid filesystem truncation (APFS max ~255 bytes)
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


def build_frontmatter(card: dict, now: str) -> str:
    folder = card.get("folder") or {}
    tags = card.get("tags") or []
    lines = [
        "---",
        f'cubox_id: "{card.get("id", "")}"',
        f'title: "{escape_yaml(str(card.get("title") or ""))}"',
        f'url: "{card.get("url", "")}"',
        f'folder: "{escape_yaml(folder.get("name", ""))}"',
        f'tags: {json.dumps(tags, ensure_ascii=False)}',
        f'ai_tags: []',
        f'created_at: "{card.get("create_time", "")}"',
        f'updated_at: "{card.get("update_time", "")}"',
        f'read: {str(card.get("read", False)).lower()}',
        f'starred: {str(card.get("starred", False)).lower()}',
        f'exported_at: "{now}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def escape_yaml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def format_annotations(annotations: list[dict]) -> str:
    if not annotations:
        return ""
    parts = ["\n\n## Annotations\n"]
    for i, ann in enumerate(annotations, 1):
        text = ann.get("text") or ann.get("content") or ""
        note = ann.get("note") or ""
        parts.append(f"### Annotation {i}\n")
        if text:
            parts.append(f"> {text}\n")
        if note:
            parts.append(f"{note}\n")
    return "\n".join(parts)


def ensure_root():
    if not (ROOT / "cubox-export-config.json").exists():
        print("错误：请在 WikiHub/ 项目根目录下运行此脚本", file=sys.stderr)
        sys.exit(1)


def build_folder_lookup(config: dict) -> dict:
    """把 folders 列表转成以 name 为 key 的字典，方便查询。"""
    lookup = {}
    for folder in config.get("folders", []):
        name = folder.get("name", "")
        if name:
            lookup[name] = folder
    return lookup


def main():
    ensure_root()
    print("Loading mapping and exported records...")
    config = load_json(MAPPING_FILE, {})
    folder_lookup = build_folder_lookup(config)
    exported = load_json(EXPORTED_FILE, {})

    print("Fetching Cubox card list...")
    cards = run_cubox(["card", "list", "--all"])
    if not isinstance(cards, list):
        print(f"Unexpected response type: {type(cards)}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(cards)} cards.")

    UNMAPPED_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    skipped = 0
    exported_count = 0
    failed = 0
    pending_items = []  # Newly exported cards awaiting agent review

    for idx, card in enumerate(cards, 1):
        card_id = str(card.get("id", ""))
        title = card.get("title") or "untitled"

        print(f"[{idx}/{len(cards)}] {title}")

        if card_id in exported:
            print(f"  -> already exported to {exported[card_id]['path']}, skipping")
            skipped += 1
            continue

        folder_name = (card.get("folder") or {}).get("name", "Uncategorized")
        folder_cfg = folder_lookup.get(folder_name, {})

        if folder_cfg.get("enabled") is False:
            print(f"  -> folder '{folder_name}' disabled, skipping")
            skipped += 1
            continue

        target_dir_str = folder_cfg.get("target_wiki", "")

        if target_dir_str:
            target_dir = ROOT / target_dir_str
        else:
            target_dir = UNMAPPED_DIR

        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            detail = run_cubox(["card", "detail", "--id", card_id])
        except subprocess.CalledProcessError as e:
            print(f"  -> FAILED to fetch detail: {e}", file=sys.stderr)
            failed += 1
            continue

        content = detail.get("content") or ""
        annotations = detail.get("annotations") or []

        filename = slugify(title) + ".md"
        file_path = unique_path(target_dir, filename)

        frontmatter = build_frontmatter(card, now)
        body = content
        if annotations:
            body += format_annotations(annotations)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + body)

        rel_path = str(file_path.relative_to(ROOT))
        exported[card_id] = {
            "title": title,
            "path": rel_path,
            "exported_at": now,
        }
        save_json(EXPORTED_FILE, exported)

        pending_items.append({
            "card_id": card_id,
            "title": title,
            "url": card.get("url", ""),
            "path": rel_path,
            "snippet": (content or "")[:2000],
        })

        print(f"  -> exported to {rel_path}")
        exported_count += 1

    if pending_items:
        save_json(PENDING_FILE, pending_items)
        print(f"\nPending review summary written to {PENDING_FILE} ({len(pending_items)} items).")
    else:
        # Ensure no stale pending file remains if nothing new was exported
        if PENDING_FILE.exists():
            PENDING_FILE.unlink()

    print("\nDone.")
    print(f"  Exported: {exported_count}")
    print(f"  Skipped (already exported): {skipped}")
    print(f"  Failed: {failed}")


if __name__ == "__main__":
    main()
