#!/usr/bin/env python3
"""创建/更新 podcast-export-config.json。

行为：
- 读取现有的 podcast-export-config.json（如果存在）。
- 若缺少默认 folder，添加一个名为 "播客 RSS 订阅"、source=rss、
  urls_file=podcast-feeds.urls、默认 enabled=false 的 folder。
- 写回配置文件并打印摘要。

用法：
    python detect-folders.py
"""

import json
import sys
from pathlib import Path

ROOT = Path.cwd()
CONFIG_FILE = ROOT / "podcast-export-config.json"


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    print("🔍 初始化播客导出配置...")

    config = load_json(CONFIG_FILE, {"folders": []})
    folders = config.get("folders", [])

    # 保留已有配置，用 name + source + urls_file 作为键
    seen = {(f.get("name"), f.get("source"), f.get("urls_file")) for f in folders}

    default_folder = {
        "name": "播客 RSS 订阅",
        "source": "rss",
        "urls_file": "podcast-feeds.urls",
        "target_wiki": "",
        "enabled": False,
    }

    if (default_folder["name"], default_folder["source"], default_folder["urls_file"]) not in seen:
        folders.append(default_folder)
        print(f"  [新增] {default_folder['name']} (enabled=false, source=rss)")
    else:
        print(f"  [保留] 播客 RSS 订阅")

    config["folders"] = folders
    if "_comment" not in config:
        config["_comment"] = (
            "podcast-export-config.json：配置需要导出的播客来源。"
            "source 为 rss 时 urls_file 中每行一个 RSS URL；source 为 urls 时每行一个节目页面或音频直链。"
            "target_wiki 留空表示进入 Unmapped/，enabled 为 false 表示跳过该来源。"
        )

    save_json(CONFIG_FILE, config)
    print(f"\n✅ 已更新：{CONFIG_FILE}")
    print(f"   共 {len(folders)} 个 folder")

    urls_file = ROOT / default_folder["urls_file"]
    if not urls_file.exists():
        urls_file.write_text("# 每行一个播客 RSS 订阅 URL\n", encoding="utf-8")
        print(f"\n📝 已创建：{urls_file}")
        print("   请在该文件中每行放一个播客 RSS 订阅 URL。")
    else:
        print(f"\n📝 已存在：{urls_file}")


if __name__ == "__main__":
    main()
