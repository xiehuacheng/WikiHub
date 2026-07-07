#!/usr/bin/env python3
"""
Export orchestration for WikiHub Select.

Reads the selection state, builds a queue JSON, and calls the main orchestrator
to import the selected items into WikiHub.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


ROOT: Path = Path.cwd()
EXPORTED_FILE: Path = ROOT / "wikihub-exported.json"
ORCHESTRATE_SCRIPT: Path = ROOT / ".claude" / "skills" / "wikihub-orchestrator" / "scripts" / "orchestrate.py"

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


def build_queue(state: dict, exported: dict | None = None) -> tuple[list[dict], int]:
    """Build an orchestrator input queue from selected items that are not yet exported.

    Returns (queue, count).
    """
    if exported is None:
        exported = _ensure_exported()

    queue: list[dict] = []
    for platform in ("xiaohongshu", "bilibili"):
        platform_state = state.get(platform, {})
        decisions = platform_state.get("decisions", {})
        for item_key, record in decisions.items():
            if record.get("decision") != "selected":
                continue
            if item_key in exported:
                continue
            url = record.get("url", "")
            if not url:
                continue
            queue.append({
                "id": item_key,
                "title": record.get("title", ""),
                "url": url,
            })
    return queue, len(queue)


def _write_queue_file(queue: list[dict]) -> Path:
    """Write queue JSON to a temp file and return its path."""
    fd, temp_path = tempfile.mkstemp(
        suffix=".json", prefix="wikihub-selected-queue-", dir=str(ROOT)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise
    return Path(temp_path)


def run_orchestrator(queue_file: Path) -> None:
    """Spawn the main orchestrator in a background thread."""
    global _export_process, _export_log, _export_started_at, _export_status

    python = shutil.which("python3") or sys.executable
    cmd = [python, str(ORCHESTRATE_SCRIPT), "--queue", str(queue_file)]

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
        # Best-effort cleanup of the temp queue file.
        try:
            queue_file.unlink()
        except FileNotFoundError:
            pass

    threading.Thread(target=_reader, daemon=True).start()


def start_export(platforms: list[str], state: dict) -> dict:
    """Build queue and start the orchestrator subprocess.

    Returns a summary of what was started.
    """
    exported = _ensure_exported()
    queue, count = build_queue(state, exported)
    if count == 0:
        return {"started": [], "queue": {"count": 0, "file": ""}}

    queue_file = _write_queue_file(queue)
    run_orchestrator(queue_file)
    return {
        "started": [{"platform": "wikihub", "count": count, "queue_file": str(queue_file)}],
        "queue": {"count": count, "file": str(queue_file)},
    }


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
