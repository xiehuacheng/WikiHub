#!/usr/bin/env python3
"""
Agent helper for wikihub-import-select.

Used by Claude Code Agent to launch the selection dashboard in the background,
then trigger export after the user has finished selecting items.

Subcommands:
    launch [--platform xiaohongshu|bilibili] [--port N]
    export
    status
    stop
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT: Path = Path.cwd()
DASHBOARD: Path = ROOT / ".claude" / "skills" / "wikihub-import-select" / "scripts" / "dashboard.py"
SYNC_SCRIPT: Path = ROOT / ".claude" / "skills" / "wikihub-import-select" / "scripts" / "sync.py"
SESSION_FILE: Path = Path("/tmp/wikihub-select-session.json")
DAEMON_LOG_FILE: Path = Path("/tmp/wikihub-select.log")


def _venv_python() -> str:
    venv = ROOT / ".claude" / "skills" / "wikihub-import-select" / ".venv" / "bin" / "python"
    if venv.exists():
        return str(venv)
    return shutil.which("python3") or sys.executable


def load_session() -> dict | None:
    if not SESSION_FILE.exists():
        return None
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _kill_pid(pid: int) -> bool:
    """Try to kill a process; return True if it was running."""
    try:
        os.kill(pid, signal.SIGTERM)
        # Give it a moment to exit gracefully.
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                return True
        # Still alive; force kill.
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return True
    except ProcessLookupError:
        return False
    except Exception as e:
        print(f"终止进程 {pid} 失败：{e}", file=sys.stderr)
        return False


def _stop_existing_dashboard() -> None:
    """Stop any existing dashboard process and clean up session file."""
    session = load_session()
    if session:
        pid = session.get("pid")
        if pid:
            if _kill_pid(pid):
                print(f"已停止旧看板进程 {pid}", file=sys.stderr)
            else:
                print(f"旧看板进程 {pid} 已不存在", file=sys.stderr)
        SESSION_FILE.unlink(missing_ok=True)

    # Fallback: kill any stray dashboard.py processes that match our script.
    try:
        result = subprocess.run(
            ["pgrep", "-f", str(DASHBOARD)],
            capture_output=True, text=True, check=False,
        )
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            try:
                pid = int(line.strip())
            except ValueError:
                continue
            if _kill_pid(pid):
                print(f"已清理残留看板进程 {pid}", file=sys.stderr)
    except Exception:
        pass


def cmd_launch(args) -> int:
    python = _venv_python()

    # Step 0: sync latest favorites into the local cache.
    if SYNC_SCRIPT.exists():
        sync_cmd = [python, str(SYNC_SCRIPT)]
        print(f"同步收藏夹缓存：{' '.join(sync_cmd)}", file=sys.stderr)
        sync_result = subprocess.run(sync_cmd, capture_output=True, text=True, cwd=str(ROOT))
        if sync_result.returncode != 0:
            print(
                f"同步收藏夹缓存失败（将使用已有缓存继续启动）：{sync_result.stderr or sync_result.stdout}",
                file=sys.stderr,
            )

    _stop_existing_dashboard()

    cmd = [python, str(DASHBOARD), "--daemon"]
    if args.platform:
        cmd += ["--platform", args.platform]
    if args.port:
        cmd += ["--port", str(args.port)]

    print(f"启动选择面板：{' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return 1

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout, end="")
        return 0

    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0
    python = _venv_python()
    cmd = [python, str(DASHBOARD), "--daemon"]
    if args.platform:
        cmd += ["--platform", args.platform]
    if args.port:
        cmd += ["--port", str(args.port)]

    print(f"启动选择面板：{' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return 1

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout, end="")
        return 0

    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def cmd_export(args) -> int:
    session = load_session()
    if not session:
        print("未找到选择面板会话，请先运行 launch", file=sys.stderr)
        return 1

    url = session.get("url", "")
    platforms = session.get("platforms", ["xiaohongshu", "bilibili"])

    print(f"触发导出：{platforms}", file=sys.stderr)
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", "-H", "Content-Type: application/json",
             "--data", json.dumps({"platforms": platforms}, ensure_ascii=False),
             f"{url}/api/export"],
            capture_output=True, text=True, check=True,
        )
        resp = json.loads(result.stdout)
        print(json.dumps(resp, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"触发导出失败：{e}", file=sys.stderr)
        return 1

    if args.no_wait:
        return 0

    print("等待导出完成...", file=sys.stderr)
    for _ in range(600):  # ~20 minutes max
        try:
            result = subprocess.run(["curl", "-s", f"{url}/api/export/status"], capture_output=True, text=True, check=True)
            status = json.loads(result.stdout)
        except Exception as e:
            print(f"获取状态失败：{e}", file=sys.stderr)
            time.sleep(2)
            continue

        log_lines = status.get("log", [])
        if log_lines:
            print("\n".join(log_lines[-5:]))
        if status.get("status") == "done":
            print("导出完成。", file=sys.stderr)
            return 0
        if status.get("status") == "failed":
            print("导出失败。", file=sys.stderr)
            return 1
        time.sleep(2)

    print("导出超时。", file=sys.stderr)
    return 1


def cmd_status(args) -> int:
    session = load_session()
    if not session:
        print("未找到选择面板会话", file=sys.stderr)
        return 1
    url = session.get("url", "")
    try:
        result = subprocess.run(["curl", "-s", f"{url}/api/export/status"], capture_output=True, text=True, check=True)
        print(result.stdout)
    except Exception as e:
        print(f"获取状态失败：{e}", file=sys.stderr)
        return 1
    return 0


def cmd_stop(args) -> int:
    _stop_existing_dashboard()
    return 0


def parse_args():
    parser = argparse.ArgumentParser(description="wikihub-select Agent helper")
    sub = parser.add_subparsers(dest="command", required=True)

    p_launch = sub.add_parser("launch", help="后台启动选择面板")
    p_launch.add_argument("--platform", default="", help="默认平台")
    p_launch.add_argument("--port", type=int, default=0, help="监听端口")

    p_export = sub.add_parser("export", help="触发导出并等待完成")
    p_export.add_argument("--no-wait", action="store_true", help="不等待完成")

    sub.add_parser("status", help="查看导出状态")
    sub.add_parser("stop", help="停止选择面板")

    return parser.parse_args()


def main():
    args = parse_args()
    if args.command == "launch":
        return cmd_launch(args)
    if args.command == "export":
        return cmd_export(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "stop":
        return cmd_stop(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
