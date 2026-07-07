#!/usr/bin/env python3
"""
WeRead（微信读书）官方 Agent Skill Gateway 的简单封装。

所有请求都通过 POST 发到 `https://i.weread.qq.com/api/agent/gateway`，
请求体为扁平 JSON，包含 `api_name`、`skill_version` 以及业务参数。
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

GATEWAY = "https://i.weread.qq.com/api/agent/gateway"
DEFAULT_SKILL_VERSION = "1.0.4"


def _load_env_file(path: Path) -> None:
    """从 KEY=VALUE 格式的 .env 文件加载环境变量（不覆盖已存在的变量）。"""
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                if (
                    len(value) >= 2
                    and value[0] == value[-1]
                    and value[0] in ('"', "'")
                ):
                    value = value[1:-1]
                if key not in os.environ:
                    os.environ[key] = value
    except Exception:
        # .env 不可读时不应阻断导出流程
        pass


_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_load_env_file(_PROJECT_ROOT / ".env")


def get_api_key() -> str:
    """优先使用已存在的环境变量，否则尝试从项目根目录 .env 加载。"""
    key = os.environ.get("WEREAD_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "未设置 WEREAD_API_KEY 环境变量。请在 .env 或 shell 中导出该变量后再试。"
        )
    return key


def call_api(api_name: str, skill_version: str = DEFAULT_SKILL_VERSION, **params) -> dict:
    """向 WeRead Agent Gateway 发起一次 POST 调用并返回 JSON。"""
    key = get_api_key()
    payload = {"api_name": api_name, "skill_version": skill_version}
    payload.update(params)

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        GATEWAY,
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"WeRead API 调用失败 ({api_name}): HTTP {e.code} - {body}") from e
    except Exception as e:
        raise RuntimeError(f"WeRead API 调用失败 ({api_name}): {e}") from e


def _extract_list(resp: dict | list | None, keys: tuple[str, ...] = ()) -> list:
    """从网关响应中尽量找出列表字段（容错不同字段名）。"""
    if resp is None:
        return []
    if isinstance(resp, list):
        return resp
    candidates = keys or ("books", "notebooks", "reviews", "updated", "data", "list", "items")
    for key in candidates:
        value = resp.get(key)
        if isinstance(value, list):
            return value
    return []


def list_notebooks(count: int = 100) -> list[dict]:
    """
    拉取有笔记的书籍列表，cursor 分页。

    请求参数：count / lastSort
    响应字段：books（书籍列表）、hasMore、sort
    """
    notebooks: list[dict] = []
    last_sort = 0
    while True:
        params: dict[str, Any] = {"count": count}
        if last_sort:
            params["lastSort"] = last_sort

        resp = call_api("/user/notebooks", **params)
        if not isinstance(resp, dict):
            break

        batch = _extract_list(resp, ("books", "notebooks", "data", "list"))
        notebooks.extend(batch)

        if not resp.get("hasMore"):
            break
        last_sort = resp.get("sort", 0)
        if not last_sort or not batch:
            # 防止死循环：如果没有拿到新数据或没有 sort 也退出
            break

    return notebooks


def get_bookmarks(book_id: str) -> tuple[list[dict], list[dict]]:
    """
    拉取一本书的划线（synckey + hasMore 分页）。

    响应字段：updated（划线列表）、chapters（章节列表）、hasMore、synckey
    返回 (highlights, chapters)
    """
    highlights: list[dict] = []
    chapters: list[dict] = []
    synckey = 0
    while True:
        params: dict[str, Any] = {"bookId": book_id}
        if synckey:
            params["synckey"] = synckey

        resp = call_api("/book/bookmarklist", **params)
        if not isinstance(resp, dict):
            break

        batch = resp.get("updated") or resp.get("bookmarks") or []
        highlights.extend(batch)

        batch_chapters = resp.get("chapters") or []
        chapters.extend(batch_chapters)

        if not resp.get("hasMore"):
            break
        synckey = resp.get("synckey", 0)
        if not synckey or not batch:
            # 防止死循环：没有新数据或没有 synckey 也退出
            break

    return highlights, chapters


def get_reviews(book_id: str, count: int = 200) -> list[dict]:
    """
    拉取一本书的个人想法/书评。

    请求参数：bookId / count / synckey
    响应字段：reviews、hasMore、synckey
    """
    reviews: list[dict] = []
    synckey = 0
    while True:
        params: dict[str, Any] = {"bookId": book_id, "count": count}
        if synckey:
            params["synckey"] = synckey

        resp = call_api("/review/list/mine", **params)
        if not isinstance(resp, dict):
            break

        batch = _extract_list(resp, ("reviews", "data", "list"))
        reviews.extend(batch)

        if not resp.get("hasMore"):
            break
        synckey = resp.get("synckey", 0)
        if not synckey or not batch:
            break

    return reviews
