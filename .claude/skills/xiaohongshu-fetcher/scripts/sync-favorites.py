#!/usr/bin/env python3
"""
通用小红书收藏夹同步工具。

调用 `xhs favorites --json` 拉取当前登录用户的收藏笔记，输出标准化 JSON 列表。
不感知 WikiHub，不读取/写入任何 WikiHub 状态文件。
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


CLI = "xhs"


def _run_xhs_favorites(cursor: str = "") -> dict:
    """调用 xhs favorites --json，返回解析后的 JSON 对象。"""
    if not shutil.which(CLI):
        raise RuntimeError(f"未找到 {CLI} 命令，请先安装 xiaohongshu-cli 并登录")

    cmd = [CLI, "favorites", "--json"]
    if cursor:
        cmd += ["--cursor", cursor]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "not_authenticated" in stderr or "登录" in stderr:
            raise RuntimeError(f"{CLI} 未登录，请先运行：xhs login")
        raise RuntimeError(f"{CLI} favorites 失败：{stderr}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"无法解析 {CLI} 输出：{e}") from e

    if not isinstance(data, dict):
        raise RuntimeError(f"{CLI} 返回非对象：{type(data).__name__}")
    if not data.get("ok"):
        error = data.get("error", {}).get("message", "unknown error")
        raise RuntimeError(f"{CLI} favorites 返回错误：{error}")
    return data.get("data", {})


def fetch_all_favorites() -> list[dict]:
    """分页拉取全部收藏笔记。"""
    all_notes = []
    cursor = ""
    for _ in range(100):  # 安全上限
        data = _run_xhs_favorites(cursor)
        notes = data.get("notes") or []
        if not isinstance(notes, list):
            break
        all_notes.extend(notes)
        cursor = data.get("cursor", "")
        if not data.get("has_more") or not cursor:
            break
    return all_notes


def normalize_note(note: dict) -> dict | None:
    """把 xhs favorites 的 note 对象转换为通用条目格式。"""
    if not isinstance(note, dict):
        return None
    note_id = str(note.get("note_id", ""))
    if not note_id:
        return None

    display_title = str(note.get("display_title", "") or note.get("title", ""))
    url = f"https://www.xiaohongshu.com/explore/{note_id}"
    user = note.get("user") or {}
    author = str(user.get("nickname", "") or user.get("nickName", ""))
    cover = note.get("cover") or {}
    cover_url = str(cover.get("url", "")) if isinstance(cover, dict) else str(cover or "")

    interact = note.get("interact_info") or note.get("interact") or {}
    liked_count = str(interact.get("liked_count", "") or interact.get("likedCount", ""))
    stats = f"👍 {liked_count}" if liked_count else ""

    return {
        "platform": "xiaohongshu",
        "item_key": f"xhs_{note_id}",
        "title": display_title,
        "url": url,
        "author": author,
        "cover": cover_url,
        "duration": "",
        "stats": stats,
        "folder": "默认收藏夹",
        "source_meta": note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="小红书收藏夹同步工具")
    parser.add_argument(
        "--output-json",
        required=True,
        help="输出 JSON 文件路径，内容为条目数组",
    )
    args = parser.parse_args()

    try:
        notes = fetch_all_favorites()
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    items = [item for item in (normalize_note(n) for n in notes) if item]
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ 小红书收藏夹同步完成：{len(items)} 条 -> {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
