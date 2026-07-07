#!/usr/bin/env python3
"""
检测当前 Cubox 账号的文件夹列表，并更新 cubox-export-config.json。

行为：
- 读取现有的 cubox-export-config.json（如果存在）。
- 调用 `cubox-cli card list --all` 获取所有卡片，提取其中的文件夹名。
- 合并结果：保留已有配置，新增文件夹默认 enabled=true、target_wiki=""。
- 写回配置文件并打印摘要。

用法：
    python detect-folders.py
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
CONFIG_FILE = ROOT / "cubox-export-config.json"


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


def main():
    print("🔍 检测 Cubox 文件夹...")
    cards = run_cubox(["card", "list", "--all"])
    if not isinstance(cards, list):
        print(f"Unexpected response type: {type(cards)}", file=sys.stderr)
        sys.exit(1)

    folder_names = set()
    for card in cards:
        folder = card.get("folder") or {}
        name = folder.get("name", "Uncategorized")
        folder_names.add(name)

    folders = sorted(folder_names)
    print(f"   发现 {len(folders)} 个文件夹\n")

    config = load_json(CONFIG_FILE, {"folders": []})
    existing = {f.get("name", ""): f for f in config.get("folders", [])}

    merged = []
    for name in folders:
        if name in existing:
            entry = existing[name]
            entry.setdefault("target_wiki", "")
            entry.setdefault("enabled", True)
            merged.append(entry)
            print(f"  [保留] {name} (enabled={entry.get('enabled')}, target_wiki='{entry.get('target_wiki')}')")
        else:
            entry = {
                "name": name,
                "target_wiki": "",
                "enabled": True,
            }
            merged.append(entry)
            print(f"  [新增] {name} (enabled=true, target_wiki='')")

    config["folders"] = merged
    if "_comment" not in config:
        config["_comment"] = "cubox-export-config.json：配置需要导出的 Cubox 文件夹。name 为 Cubox 中的文件夹名，target_wiki 留空表示不进映射直接到 Unmapped，enabled 为 false 表示跳过该文件夹。"

    save_json(CONFIG_FILE, config)
    print(f"\n✅ 已更新：{CONFIG_FILE}")
    print(f"   共 {len(merged)} 个文件夹")


if __name__ == "__main__":
    main()
