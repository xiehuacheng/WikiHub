#!/usr/bin/env python3
"""
WikiHub Select - Local web dashboard.

Launches a FastAPI server that serves a single-page dashboard for reviewing
Xiaohongshu and Bilibili favorites and deciding which items to export.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path


ROOT: Path = Path.cwd()
SCRIPTS_DIR: Path = ROOT / ".claude" / "skills" / "wikihub-orchestrator" / "scripts"
ASSETS_DIR: Path = ROOT / ".claude" / "skills" / "wikihub-orchestrator" / "assets"
EXPORTED_FILE: Path = ROOT / "wikihub-exported.json"

sys.path.insert(0, str(SCRIPTS_DIR))
import select_exporter as exporter
import select_platforms as platforms
import select_state as state


def _load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def _counts_for_platform(st: dict, exported: dict, platform: str, items: list[dict]) -> dict:
    decisions = st.get(platform, {}).get("decisions", {})
    pending = state.get_pending_items(items, st, exported, platform)
    return {
        "pending": len(pending),
        "selected": sum(1 for d in decisions.values() if d.get("decision") == "selected"),
        "rejected": sum(1 for d in decisions.values() if d.get("decision") == "rejected"),
        "skipped": sum(1 for d in decisions.values() if d.get("decision") == "skipped"),
        "exported": sum(1 for item in items if item.get("item_key", "") in exported),
    }


def _build_api_app():
    from fastapi import FastAPI, Query
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel

    app = FastAPI(title="WikiHub Select")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        index_path = ASSETS_DIR / "index.html"
        if index_path.exists():
            html = index_path.read_text(encoding="utf-8")
            default_platform = os.environ.get("SELECT_DEFAULT_PLATFORM", "xiaohongshu")
            config_script = f'<script>window.DEFAULT_PLATFORM = {json.dumps(default_platform)};</script>'
            html = html.replace("</head>", config_script + "\n  </head>")
            return html
        return HTMLResponse(content="<h1>WikiHub Select</h1><p>index.html not found.</p>", status_code=404)

    @app.get("/api/state")
    async def api_state():
        st = state.load_state()
        exported = _load_json(EXPORTED_FILE, {})
        all_items = platforms.load_all_items()
        return {
            "platforms": {
                platform: _counts_for_platform(st, exported, platform, all_items.get(platform, []))
                for platform in ("xiaohongshu", "bilibili")
            },
        }

    @app.get("/api/items")
    async def api_items(
        platform: str = Query(..., pattern="^(xiaohongshu|bilibili)$"),
        status: str = Query("pending", pattern="^(pending|selected|rejected|skipped)$"),
        q: str = Query(""),
    ):
        st = state.load_state()
        exported = _load_json(EXPORTED_FILE, {})

        if status == "pending":
            items = platforms.load_all_items().get(platform, [])
            items = state.get_pending_items(items, st, exported, platform)
        else:
            decisions = st.get(platform, {}).get("decisions", {})
            items = [
                {
                    "platform": platform,
                    "item_key": item_key,
                    "title": record.get("title", ""),
                    "url": record.get("url", ""),
                    "author": record.get("author", ""),
                    "cover": record.get("cover", ""),
                    "duration": "",
                    "stats": "",
                    "folder": "",
                    "decision": record.get("decision"),
                }
                for item_key, record in decisions.items()
                if record.get("decision") == status
            ]

        if q:
            q_lower = q.lower()
            items = [
                item for item in items
                if q_lower in item.get("title", "").lower()
                or q_lower in item.get("author", "").lower()
            ]

        return {"items": items, "count": len(items)}

    class DecisionRequest(BaseModel):
        platform: str
        item_key: str
        decision: str

    @app.post("/api/decision")
    async def api_decision(req: DecisionRequest):
        if req.decision not in state.VALID_DECISIONS:
            return JSONResponse(
                status_code=400,
                content={"error": f"invalid decision: {req.decision}"},
            )
        st = state.load_state()
        # Reconstruct minimal item metadata from the pending list if available.
        all_items = platforms.load_all_items()
        item = next(
            (i for i in all_items.get(req.platform, []) if i.get("item_key") == req.item_key),
            {},
        )
        state.set_decision(st, req.platform, req.item_key, req.decision, item)
        state.save_state(st)
        return {"ok": True}

    class BulkDecisionRequest(BaseModel):
        platform: str
        decisions: list[dict]

    @app.post("/api/decision/bulk")
    async def api_decision_bulk(req: BulkDecisionRequest):
        st = state.load_state()
        all_items = platforms.load_all_items()
        for entry in req.decisions:
            item_key = entry.get("item_key", "")
            decision = entry.get("decision", "")
            if decision not in state.VALID_DECISIONS:
                continue
            item = next(
                (i for i in all_items.get(req.platform, []) if i.get("item_key") == item_key),
                {},
            )
            state.set_decision(st, req.platform, item_key, decision, item)
        state.save_state(st)
        return {"ok": True}

    class ExportRequest(BaseModel):
        platforms: list[str] | None = None

    @app.post("/api/export")
    async def api_export(req: ExportRequest):
        st = state.load_state()
        # platforms parameter is kept for API compatibility but we always export
        # the full selected queue across both platforms.
        result = exporter.start_export(req.platforms or ["xiaohongshu", "bilibili"], st)
        return {"ok": True, "result": result}

    @app.get("/api/export/status")
    async def api_export_status():
        return exporter.get_export_status()

    @app.post("/api/export/reset")
    async def api_export_reset():
        exporter.reset_export_status()
        return {"ok": True}

    @app.get("/api/review")
    async def api_review(q: str = Query("")):
        st = state.load_state()
        items = []
        for platform in ("xiaohongshu", "bilibili"):
            for item_key, record in st.get(platform, {}).get("decisions", {}).items():
                items.append({
                    "platform": platform,
                    "item_key": item_key,
                    "title": record.get("title", ""),
                    "url": record.get("url", ""),
                    "author": record.get("author", ""),
                    "cover": record.get("cover", ""),
                    "duration": "",
                    "stats": "",
                    "folder": "",
                    "decision": record.get("decision"),
                    "decided_at": record.get("decided_at", ""),
                })
        items.sort(key=lambda x: x.get("decided_at", ""), reverse=True)
        if q:
            q_lower = q.lower()
            items = [
                item for item in items
                if q_lower in item.get("title", "").lower()
                or q_lower in item.get("author", "").lower()
                or q_lower in item.get("platform", "").lower()
            ]
        return {"items": items, "count": len(items)}

    @app.get("/api/folders")
    async def api_folders(platform: str = Query(..., pattern="^(xiaohongshu|bilibili)$")):
        if platform == "bilibili":
            return {"folders": platforms.load_bilibili_folders()}
        return {"folders": []}

    class FolderToggleRequest(BaseModel):
        platform: str
        folder_id: str

    @app.post("/api/folders/toggle")
    async def api_folders_toggle(req: FolderToggleRequest):
        if req.platform == "bilibili":
            try:
                result = platforms.toggle_bilibili_folder(req.folder_id)
                return {"ok": True, "folder": result}
            except ValueError as e:
                return JSONResponse(status_code=404, content={"error": str(e)})
        return JSONResponse(status_code=400, content={"error": "platform not supported"})

    app.mount("/static", StaticFiles(directory=ASSETS_DIR), name="static")
    return app


def _find_free_port(start: int) -> int:
    port = start
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1


SESSION_FILE: Path = Path("/tmp/wikihub-select-session.json")
DAEMON_LOG_FILE: Path = Path("/tmp/wikihub-select.log")


def _write_session(url: str, pid: int, platforms: list[str]) -> None:
    import tempfile
    data = {
        "url": url,
        "pid": pid,
        "platforms": platforms,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    fd, tmp = tempfile.mkstemp(prefix=".tmp-wikihub-select-session-", dir=str(SESSION_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SESSION_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _daemonize(argv: list[str], port: int) -> int:
    """Relaunch the script in the background and return the new PID."""
    # Remove --daemon from argv for the child so it runs normally.
    child_argv = [a for a in argv if a != "--daemon"]
    # Force --no-open in child to avoid browser popups.
    if "--no-open" not in child_argv:
        child_argv.append("--no-open")
    log_path = str(DAEMON_LOG_FILE)
    with open(log_path, "a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable] + child_argv,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            start_new_session=True,
        )
    return proc.pid


def parse_args():
    parser = argparse.ArgumentParser(description="WikiHub Select 本地 Web 选择面板")
    parser.add_argument("--port", type=int, default=0, help="监听端口（默认 7321）")
    parser.add_argument("--platform", default="", help="默认激活的平台（xiaohongshu/bilibili）")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--daemon", action="store_true", help="后台运行（供 Agent 调用）")
    return parser.parse_args()


def main():
    args = parse_args()
    port = args.port or int(os.environ.get("PORT", "7321"))
    port = _find_free_port(port)

    if args.platform in ("xiaohongshu", "bilibili"):
        os.environ["SELECT_DEFAULT_PLATFORM"] = args.platform

    # Ensure assets directory exists before mounting.
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    if args.daemon:
        platforms_list = [args.platform] if args.platform in ("xiaohongshu", "bilibili") else ["xiaohongshu", "bilibili"]
        pid = _daemonize(sys.argv, port)
        url = f"http://127.0.0.1:{port}"
        # Wait briefly for the child to bind; if it fails we'll still report the URL.
        import time
        time.sleep(0.5)
        _write_session(url, pid, platforms_list)
        print(json.dumps({"url": url, "pid": pid, "platforms": platforms_list}, ensure_ascii=False))
        return

    app = _build_api_app()

    url = f"http://127.0.0.1:{port}"
    print(f"🚀 WikiHub Select 已启动：{url}")
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
