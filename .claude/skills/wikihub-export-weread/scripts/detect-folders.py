#!/usr/bin/env python3
"""
初始化微信读书导出配置并检测运行环境。

行为：
- 读取现有的 weread-export-config.json（如果存在）。
- 检测 WEREAD_API_KEY 是否可用，并尝试调用 list_notebooks(count=20) 验证。
- 保证配置文件中存在默认条目（全部笔记，默认禁用）。
- 写回配置文件并打印摘要。

用法：
    python detect-folders.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weread_api


ROOT = Path.cwd()
CONFIG_FILE = ROOT / "weread-export-config.json"
DEFAULT_FOLDER_NAME = "微信读书全部笔记"


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    print("🔍 检测微信读书导出环境...\n", flush=True)

    # 检查 API Key 是否可用
    api_ok = False
    try:
        weread_api.get_api_key()
        api_ok = True
        print("  ✅ 检测到 WEREAD_API_KEY")
    except RuntimeError as e:
        print(f"  ⚠️  {e}", file=sys.stderr)
        print()

    # 尝试调用接口验证
    notebook_count = None
    if api_ok:
        try:
            notebooks = weread_api.list_notebooks(count=20)
            notebook_count = len(notebooks)
            print(f"  ✅ 成功连接微信读书 Skill Gateway（发现 {notebook_count} 本有笔记的书）")
        except Exception as e:
            api_ok = False
            print(f"  ⚠️  无法拉取笔记书籍列表：{e}", file=sys.stderr)

    config = load_json(CONFIG_FILE, {"folders": []})
    existing = {f.get("name", ""): f for f in config.get("folders", [])}

    # 保证默认“全部笔记”条目存在
    if DEFAULT_FOLDER_NAME not in existing:
        config["folders"].append({
            "name": DEFAULT_FOLDER_NAME,
            "source": "notebooks",
            "target_wiki": "",
            "enabled": False,
        })
        print(f"  [新增] {DEFAULT_FOLDER_NAME}（source=notebooks，默认禁用）")

    # 保证所有条目都有必需的字段
    for folder in config.get("folders", []):
        folder.setdefault("source", "notebooks")
        folder.setdefault("target_wiki", "")
        folder.setdefault("enabled", True)

    if "_comment" not in config:
        config["_comment"] = (
            "weread-export-config.json：配置微信读书笔记导出。"
            "source=notebooks 拉取全部有笔记的书籍。"
            "target_wiki 留空表示不进映射直接到 Unmapped，enabled 为 false 表示跳过该 folder。"
        )

    save_json(CONFIG_FILE, config)
    print(f"\n✅ 已更新：{CONFIG_FILE}")
    print(f"   共 {len(config.get('folders', []))} 个 folder 配置")
    if api_ok and notebook_count is not None:
        print(f"   当前账号有 {notebook_count} 本带笔记的书籍可供导出")
    elif not api_ok:
        print("\n提示：当前未成功连接微信读书 Skill Gateway，请检查 WEREAD_API_KEY 后再运行导出。")


if __name__ == "__main__":
    main()
