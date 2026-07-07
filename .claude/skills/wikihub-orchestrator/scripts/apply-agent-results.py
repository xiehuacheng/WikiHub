#!/usr/bin/env python3
"""
Apply agent-driven validation/classification results to exported files.

Reads /tmp/wikihub-agent-results.json (produced by the orchestrating agent)
and performs concrete actions:
- Quarantine mismatched articles (move to Quarantine/)
- Write ai_tags to wikihub-tags.json
- Update markdown frontmatter and wikihub-exported.json
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd()
EXPORTED_FILE = ROOT / "wikihub-exported.json"
TAGS_FILE = ROOT / "wikihub-tags.json"
RESULTS_FILE = Path("/tmp/wikihub-agent-results.json")
QUARANTINE_DIR = ROOT / "Quarantine"


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_ROOT_MARKERS = [
    ".claude/skills/wikihub-orchestrator/wikihub-orchestrator-config.json",
    "wikihub-orchestrator-config.json",
    "Makefile",
]


def ensure_root():
    if not any((ROOT / name).exists() for name in _ROOT_MARKERS):
        print("错误：请在 WikiHub/ 项目根目录下运行此脚本", file=sys.stderr)
        sys.exit(1)


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


def move_with_assets(src: Path, dst: Path):
    """移动 Markdown 文件时，同步移动同名的 .assets/ 目录（如果存在）。"""
    shutil.move(str(src), str(dst))
    src_assets = src.parent / f"{src.stem}.assets"
    if src_assets.exists():
        dst_assets = dst.parent / f"{dst.stem}.assets"
        # 如果目标 assets 目录已存在，使用唯一名称
        if dst_assets.exists():
            dst_assets = unique_path(dst.parent, f"{dst.stem}.assets")
        shutil.move(str(src_assets), str(dst_assets))


def update_frontmatter(file_path: Path, ai_tags: list[str], quarantine_reason: str | None):
    text = file_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False

    parts = text.split("---", 2)
    if len(parts) < 3:
        return False

    fm = parts[1]
    body = parts[2]

    # Update ai_tags
    tags_json = json.dumps(ai_tags, ensure_ascii=False)
    if "ai_tags:" in fm:
        fm_lines = fm.rstrip().split("\n")
        new_lines = []
        for line in fm_lines:
            if line.startswith("ai_tags:"):
                new_lines.append(f"ai_tags: {tags_json}")
            else:
                new_lines.append(line)
        fm = "\n".join(new_lines)
    else:
        fm = fm.rstrip() + f"\nai_tags: {tags_json}"

    # Update quarantine reason if present
    if quarantine_reason:
        reason_escaped = quarantine_reason.replace("\\", "\\\\").replace('"', '\\"')
        if "quarantine_reason:" in fm:
            fm_lines = fm.rstrip().split("\n")
            new_lines = []
            for line in fm_lines:
                if line.startswith("quarantine_reason:"):
                    new_lines.append(f'quarantine_reason: "{reason_escaped}"')
                else:
                    new_lines.append(line)
            fm = "\n".join(new_lines)
        else:
            fm = fm.rstrip() + f'\nquarantine_reason: "{reason_escaped}"'

    body = body.lstrip("\n")
    new_text = f"---{fm}\n---\n\n{body}"
    file_path.write_text(new_text, encoding="utf-8")
    return True


def main():
    ensure_root()

    if not RESULTS_FILE.exists():
        print(f"No agent results found at {RESULTS_FILE}. Nothing to apply.")
        return

    exported = load_json(EXPORTED_FILE, {})
    tags = load_json(TAGS_FILE, {})
    results = load_json(RESULTS_FILE, {})

    QUARANTINE_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    quarantined = 0
    tagged = 0
    failed = []

    for card_id, result in results.items():
        card_id = str(card_id)
        if card_id not in exported:
            failed.append(f"{card_id}: not found in exported records")
            continue

        record = exported[card_id]
        file_path = ROOT / record["path"]
        if not file_path.exists():
            failed.append(f"{card_id}: file not found {file_path}")
            continue

        is_quarantine = bool(result.get("quarantine"))
        ai_tags = result.get("ai_tags") or []
        quarantine_reason = result.get("quarantine_reason")

        if is_quarantine:
            # Move to Quarantine directory
            target_path = unique_path(QUARANTINE_DIR, file_path.name)
            try:
                move_with_assets(file_path, target_path)
            except Exception as e:
                failed.append(f"{card_id}: failed to move to quarantine: {e}")
                continue

            rel_path = str(target_path.relative_to(ROOT))
            record["path"] = rel_path
            record["quarantined_at"] = now
            if quarantine_reason:
                record["quarantine_reason"] = quarantine_reason

            # Update frontmatter with quarantine reason (no ai_tags needed)
            update_frontmatter(target_path, ai_tags, quarantine_reason)

            quarantined += 1
            print(f"Quarantined: {file_path.name} -> {rel_path}")
        else:
            # Write tags
            tags[card_id] = ai_tags
            record["ai_tags"] = ai_tags

            # Update frontmatter
            if update_frontmatter(file_path, ai_tags, None):
                tagged += 1
            else:
                failed.append(f"{card_id}: failed to update frontmatter")
                continue

            print(f"Tagged: {file_path.name} -> {ai_tags}")

    save_json(EXPORTED_FILE, exported)
    save_json(TAGS_FILE, tags)

    print("\nDone.")
    print(f"  Quarantined: {quarantined}")
    print(f"  Tagged: {tagged}")
    if failed:
        print(f"  Failed: {len(failed)}")
        for item in failed:
            print(f"    - {item}")


if __name__ == "__main__":
    main()
