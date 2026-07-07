#!/usr/bin/env python3
"""
Export orchestration for wikihub-select.

Reads the selection state, writes platform-specific .urls files, and spawns the
existing export scripts (export-xiaohongshu.py / export-bilibili.py) with --yes.
"""

import json
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path


ROOT: Path = Path.cwd()
EXPORTED_FILE: Path = ROOT / "wikihub-exported.json"

EXPORT_SCRIPTS = {
    "xiaohongshu": ROOT / ".claude" / "skills" / "wikihub-export-xiaohongshu" / "scripts" / "export-xiaohongshu.py",
    "bilibili": ROOT / ".claude" / "skills" / "wikihub-export-bilibili" / "scripts" / "export-bilibili.py",
}


_lock = threading.Lock()
_export_process: subprocess.Popen | None = None
_export_log: list[str] = []
_export_started_at: str | None = None
_export_status: str = "idle"  # idle | running | done | failed


def _load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def _ensure_exported() -> dict:
    return _load_json(EXPORTED_FILE, {})


def _urls_file_path(state: dict, platform: str) -> Path:
    platform_state = state.get(platform, {})
    urls_file = platform_state.get("urls_file", f"{platform}-selected.urls")
    return ROOT / urls_file


def write_selected_urls(state: dict, exported: dict | None = None) -> dict[str, tuple[int, Path]]:
    """Write .urls files for all selected items that are not yet exported.

    Returns a mapping of platform -> (count, urls_file_path).
    """
    if exported is None:
        exported = _ensure_exported()

    results: dict[str, tuple[int, Path]] = {}
    for platform in ("xiaohongshu", "bilibili"):
        platform_state = state.get(platform, {})
        decisions = platform_state.get("decisions", {})
        urls_path = _urls_file_path(state, platform)

        selected = [
            record["url"]
            for item_key, record in decisions.items()
            if record.get("decision") == "selected"
            and item_key not in exported
            and record.get("url")
        ]

        if selected:
            urls_path.write_text("\n".join(selected) + "\n", encoding="utf-8")
        elif urls_path.exists():
            # Keep the file but empty it so stale URLs are not re-exported.
            urls_path.write_text("", encoding="utf-8")

        results[platform] = (len(selected), urls_path)

    return results


def export_platform(platform: str, urls_file: Path) -> None:
    """Spawn the export script for a platform in a background thread."""
    global _export_process, _export_log, _export_started_at, _export_status

    script = EXPORT_SCRIPTS.get(platform)
    if not script or not script.exists():
        raise RuntimeError(f"未找到 {platform} 导出脚本：{script}")

    python = shutil.which("python3") or sys.executable
    cmd = [python, str(script), "--urls-file", str(urls_file), "--yes"]

    with _lock:
        if _export_process is not None and _export_process.poll() is None:
            raise RuntimeError("已有导出任务在运行")
        _export_log = []
        _export_started_at = datetime.now(timezone.utc).isoformat()
        _export_status = "running"
        _export_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(ROOT),
        )

    def _reader():
        global _export_status
        if _export_process is None or _export_process.stdout is None:
            return
        for line in _export_process.stdout:
            with _lock:
                _export_log.append(line.rstrip("\n"))
        _export_process.wait()
        with _lock:
            _export_status = "done" if _export_process.returncode == 0 else "failed"

    threading.Thread(target=_reader, daemon=True).start()


def start_export(platforms: list[str], state: dict) -> dict:
    """Write .urls files and start export subprocesses for the given platforms.

    Returns a summary of what was started.
    """
    exported = _ensure_exported()
    written = write_selected_urls(state, exported)
    started = []
    for platform in platforms:
        count, urls_path = written[platform]
        if count == 0:
            continue
        export_platform(platform, urls_path)
        started.append({"platform": platform, "count": count, "urls_file": str(urls_path)})
    return {"started": started, "written": {p: {"count": c, "urls_file": str(path)} for p, (c, path) in written.items()}}


def get_export_status() -> dict:
    """Return current export status and recent log lines."""
    with _lock:
        return {
            "status": _export_status,
            "started_at": _export_started_at,
            "log": list(_export_log),
            "running": _export_process is not None and _export_process.poll() is None,
        }


def reset_export_status() -> None:
    """Reset internal export tracking (used after the UI has consumed a done/failed state)."""
    global _export_process, _export_log, _export_started_at, _export_status
    with _lock:
        _export_process = None
        _export_log = []
        _export_started_at = None
        _export_status = "idle"
