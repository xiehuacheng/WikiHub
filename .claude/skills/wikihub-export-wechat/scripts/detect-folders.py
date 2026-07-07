#!/usr/bin/env python3
"""
初始化/更新 wechat-export-config.json。

行为：
- 读取现有的 wechat-export-config.json（如果存在）。
- 默认添加一个名为 "微信公众号文章列表"、source=urls、urls_file=wechat-articles.urls 的 folder。
- 保留已有配置，新增 folder 默认 enabled=false、target_wiki=""。
- 写回配置文件并打印摘要。

用法：
    python detect-folders.py
"""

import json
import sys
from pathlib import Path

ROOT = Path.cwd()
CONFIG_FILE = ROOT / "wechat-export-config.json"
DEFAULT_URLS_FILE = "wechat-articles.urls"


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    print("🔍 初始化微信公众号导出配置...")

    config = load_json(CONFIG_FILE, {"folders": []})
    existing = {f.get("name", ""): f for f in config.get("folders", [])}

    merged = []
    for name, folder in existing.items():
        entry = folder.copy()
        entry.setdefault("source", "urls")
        entry.setdefault("urls_file", DEFAULT_URLS_FILE)
        entry.setdefault("target_wiki", "")
        entry.setdefault("enabled", False)
        merged.append(entry)
        print(f"  [保留] {name} (enabled={entry.get('enabled')}, target_wiki='{entry.get('target_wiki')}')")

    default_name = "微信公众号文章列表"
    if default_name not in existing:
        entry = {
            "name": default_name,
            "source": "urls",
            "urls_file": DEFAULT_URLS_FILE,
            "target_wiki": "",
            "enabled": False,
        }
        merged.append(entry)
        print(f"  [新增] {default_name} (enabled=false, target_wiki='', urls_file='{DEFAULT_URLS_FILE}')")

    config["folders"] = merged
    if "_comment" not in config:
        config["_comment"] = "wechat-export-config.json：配置需要导出的微信公众号文章列表。source 为 urls 时读取 urls_file 中的链接（每行一个），target_wiki 留空表示不进映射直接到 Unmapped，enabled 为 false 表示跳过该列表。"

    save_json(CONFIG_FILE, config)
    print(f"\n✅ 已更新：{CONFIG_FILE}")
    print(f"   共 {len(merged)} 个 folder")

    urls_path = ROOT / DEFAULT_URLS_FILE
    if not urls_path.exists():
        urls_path.write_text("", encoding="utf-8")
        print(f"\n📝 已创建空文件：{urls_path}")
        print("   请在该文件中每行放一个公众号文章链接。")
    else:
        print(f"\n📝 URL 文件已存在：{urls_path}")


if __name__ == "__main__":
    main()
