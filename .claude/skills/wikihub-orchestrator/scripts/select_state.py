#!/usr/bin/env python3
"""
State management for wikihub-selection-state.json.

Tracks per-platform selection decisions (selected / rejected / skipped) for
xiaohongshu and bilibili favorites.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT: Path = Path.cwd()
STATE_FILE: Path = ROOT / "wikihub-selection-state.json"

VALID_DECISIONS = {"selected", "rejected", "skipped"}


def load_state() -> dict:
    """Load selection state from STATE_FILE, or return a fresh state."""
    if not STATE_FILE.exists():
        return init_state()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return init_state()
        # Ensure required sections exist.
        for platform in ("xiaohongshu", "bilibili"):
            if platform not in data or not isinstance(data[platform], dict):
                data[platform] = {"urls_file": f"{platform}-selected.urls", "decisions": {}}
            if "decisions" not in data[platform]:
                data[platform]["decisions"] = {}
        return data
    except Exception:
        return init_state()


def save_state(state: dict) -> None:
    """Atomically write state to STATE_FILE via a temporary file + rename."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp-wikihub-selection-state-",
        dir=str(STATE_FILE.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def get_platform_state(state: dict, platform: str) -> dict:
    """Return the state slice for a platform, creating defaults if missing."""
    if platform not in state or not isinstance(state[platform], dict):
        urls_file = f"{platform}-selected.urls"
        state[platform] = {"urls_file": urls_file, "decisions": {}}
    return state[platform]


def _extract_source_id(platform: str, item_key: str) -> str:
    """Map an item_key back to the id used in wikihub-exported.json."""
    if platform == "xiaohongshu" and item_key.startswith("xhs_"):
        return item_key[4:]
    return item_key


def set_decision(
    state: dict,
    platform: str,
    item_key: str,
    decision: str,
    item: dict,
) -> None:
    """Record a decision for an item.

    decision must be one of "selected", "rejected", "skipped".
    """
    if decision not in VALID_DECISIONS:
        raise ValueError(f"Invalid decision: {decision}. Must be one of {VALID_DECISIONS}")

    platform_state = get_platform_state(state, platform)
    platform_state["decisions"][item_key] = {
        "decision": decision,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "author": item.get("author", ""),
        "cover": item.get("cover", ""),
    }


def get_decision(state: dict, platform: str, item_key: str) -> str | None:
    """Return the decision for an item, or None if not decided."""
    platform_state = get_platform_state(state, platform)
    return platform_state["decisions"].get(item_key, {}).get("decision")


def list_decisions(
    state: dict,
    platform: str,
    decision_filter: str | None = None,
) -> dict[str, dict]:
    """Return all decisions for a platform, optionally filtered by decision type."""
    platform_state = get_platform_state(state, platform)
    decisions = platform_state["decisions"]
    if decision_filter is None:
        return dict(decisions)
    return {
        key: record
        for key, record in decisions.items()
        if record.get("decision") == decision_filter
    }


def get_pending_items(
    all_items: list[dict],
    state: dict,
    exported: dict,
    platform: str,
) -> list[dict]:
    """Return items that are neither exported nor have an existing decision."""
    platform_state = get_platform_state(state, platform)
    decisions = platform_state["decisions"]
    pending = []
    for item in all_items:
        item_key = item.get("item_key", "")
        if not item_key:
            continue
        # wikihub-exported.json keys match item_key exactly
        # (xhs_<note_id> for xiaohongshu, bilibili_<bvid> for bilibili).
        if item_key in exported:
            continue
        if item_key in decisions:
            continue
        pending.append(item)
    return pending


def init_state() -> dict:
    """Return a fresh selection state structure."""
    return {
        "version": 1,
        "xiaohongshu": {
            "urls_file": "xiaohongshu-selected.urls",
            "decisions": {},
        },
        "bilibili": {
            "urls_file": "bilibili-selected.urls",
            "decisions": {},
        },
    }
