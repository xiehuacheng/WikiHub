#!/usr/bin/env python3
"""
初始化小红书导出配置并检测运行环境。

行为：
- 读取现有的 xiaohongshu-export-config.json（如果存在）。
- 检测 `xhs` CLI 是否可用以及是否已登录（通过 `xhs status` 或 `xhs favorites`）。
- 若 CLI 已登录，调用 `xhs favorites --json` 生成 `xiaohongshu-favorites.urls` 全量收藏 URL 文件。
- 保证配置文件中存在默认条目（全部收藏，默认禁用）。
- 校验用户配置的 urls_file 是否存在。
- 写回配置文件并打印摘要。

用法：
    python detect-folders.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import xhs_cli


ROOT = Path.cwd()
CONFIG_FILE = ROOT / "xiaohongshu-export-config.json"
DEFAULT_FAVORITES_FILE = "xiaohongshu-favorites.urls"


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_favorites_urls_file(output_path: Path) -> int:
    """通过 xhs CLI 生成全量收藏 URL 文件，返回写入的 URL 数量。"""
    notes = xhs_cli.list_favorite_notes()
    urls = [meta.get("url") or f"https://www.xiaohongshu.com/explore/{meta.get('note_id', '')}" for meta in notes]
    output_path.write_text("\n".join(urls) + "\n", encoding="utf-8")
    return len(urls)


def validate_urls_files(config: dict) -> list[str]:
    """校验配置中 source=urls 的 urls_file 是否存在，返回缺失文件列表。"""
    missing = []
    for folder in config.get("folders", []):
        if folder.get("source") == "urls":
            urls_file = folder.get("urls_file", "")
            if urls_file and not (ROOT / urls_file).exists():
                missing.append(urls_file)
    return missing


def main():
    print("🔍 检测小红书导出环境...\n", flush=True)

    # 检查 xhs CLI 是否已安装并登录
    try:
        xhs_cli.ensure_ready()
        cli_ok = True
        print("  ✅ 检测到 xhs CLI 并已登录")
    except RuntimeError as e:
        print(f"  ⚠️  {e}", file=sys.stderr)
        cli_ok = False
        print()

    config = load_json(CONFIG_FILE, {"folders": []})
    existing = {f.get("name", ""): f for f in config.get("folders", [])}

    # 生成全量收藏 URL 文件（如果 CLI 已登录）
    favorites_count = 0
    if cli_ok:
        try:
            favorites_count = generate_favorites_urls_file(ROOT / DEFAULT_FAVORITES_FILE)
            print(f"  ✅ 已生成全量收藏 URL 文件：{DEFAULT_FAVORITES_FILE}（{favorites_count} 条）")
        except Exception as e:
            print(f"  ⚠️  生成全量收藏 URL 文件失败：{e}", file=sys.stderr)

    # 保证默认“全部收藏”条目存在
    if "小红书全部收藏" not in existing:
        config["folders"].append({
            "name": "小红书全部收藏",
            "source": "favorites",
            "urls_file": DEFAULT_FAVORITES_FILE,
            "target_wiki": "",
            "enabled": False,
        })
        print(f"  [新增] 小红书全部收藏（source=favorites，默认禁用）")

    # 保证所有条目都有必需的字段
    for folder in config.get("folders", []):
        folder.setdefault("source", "urls")
        folder.setdefault("urls_file", "")
        folder.setdefault("target_wiki", "")
        folder.setdefault("enabled", True)

    # 校验 urls_file
    missing = validate_urls_files(config)
    if missing:
        print(f"\n⚠️  以下 urls_file 不存在，请创建或更新配置：")
        for f in missing:
            print(f"   - {f}")

    if "_comment" not in config:
        config["_comment"] = (
            "xiaohongshu-export-config.json：配置小红书收藏夹导入。"
            "source=favorites 调用 xhs favorites --json；source=urls 读取 urls_file。"
            "target_wiki 留空表示不进映射直接到 Unmapped，enabled 为 false 表示跳过该收藏夹。"
        )

    save_json(CONFIG_FILE, config)
    print(f"\n✅ 已更新：{CONFIG_FILE}")
    print(f"   共 {len(config.get('folders', []))} 个收藏夹配置")
    if not cli_ok:
        print("\n提示：当前未使用 xhs CLI，您可以通过创建 .urls 文件并配置 source=urls 来导入指定笔记。")


if __name__ == "__main__":
    main()
