#!/usr/bin/env python3
"""
通用 Cubox 卡片列表获取工具。

通过 cubox-cli 拉取所有卡片，排除指定归档文件夹后，输出为 JSON 数组。
该工具不感知 WikiHub，不读取/写入任何 WikiHub 特定状态文件。
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_ARCHIVE_FOLDER = "WikiHub_已归档"


class CuboxCliError(Exception):
    """cubox-cli 调用失败或返回非预期结果。"""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.message = message
        self.stderr = stderr


def run_cubox_card_list() -> list[dict]:
    """调用 cubox-cli 获取所有卡片，返回原始卡片列表。"""
    cmd = ["cubox-cli", "card", "list", "--all", "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if any(k in stderr.lower() for k in ("auth", "login", "unauthorized")):
            raise CuboxCliError(
                "cubox-cli 未认证，请先运行：cubox-cli auth login", stderr
            )
        raise CuboxCliError(
            f"cubox-cli 调用失败：{' '.join(cmd)}\n{stderr}", stderr
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise CuboxCliError(f"无法解析 cubox-cli 输出：{e}", result.stderr)
    if not isinstance(data, list):
        raise CuboxCliError(
            f"cubox-cli card list 返回非列表类型：{type(data).__name__}", ""
        )
    return data


def get_domain(url: str) -> str:
    """提取 URL 的 netloc，并移除 www. 前缀。"""
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def exclude_archive_cards(cards: list[dict], archive_name: str) -> list[dict]:
    """排除位于归档文件夹中的卡片。"""
    result = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        folder = card.get("folder") or {}
        names = {folder.get("nested_name"), folder.get("name")}
        if archive_name not in names:
            result.append(card)
    return result


def normalize_card(card: dict) -> dict:
    """将 cubox-cli 原始卡片格式化为通用输出结构。"""
    folder = card.get("folder") or {}
    return {
        "id": str(card.get("id", "")),
        "title": card.get("title", "") or "",
        "url": card.get("url", "") or "",
        "domain": get_domain(card.get("url", "")),
        "folder": {
            "id": str(folder.get("id", "")) if folder.get("id") is not None else "",
            "name": folder.get("name", "") or "",
            "nested_name": folder.get("nested_name", "")
            or folder.get("name", "")
            or "",
        },
        "create_time": card.get("create_time", "") or "",
        "update_time": card.get("update_time", "") or "",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="通用 Cubox 卡片列表获取工具：输出未归档卡片 JSON。"
    )
    parser.add_argument(
        "--output-json",
        required=True,
        help="输出卡片列表的 JSON 文件路径。",
    )
    parser.add_argument(
        "--archive-folder",
        default=DEFAULT_ARCHIVE_FOLDER,
        help=f"要排除的归档文件夹名称（默认：{DEFAULT_ARCHIVE_FOLDER}）。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive_name = args.archive_folder or DEFAULT_ARCHIVE_FOLDER

    try:
        cards = run_cubox_card_list()
    except CuboxCliError as e:
        print(f"❌ {e.message}", file=sys.stderr)
        if e.stderr:
            print(f"   详细错误：{e.stderr}", file=sys.stderr)
        return 1

    cards = exclude_archive_cards(cards, archive_name)
    normalized = [normalize_card(c) for c in cards]

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"已写入 {len(normalized)} 张卡片到 {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
