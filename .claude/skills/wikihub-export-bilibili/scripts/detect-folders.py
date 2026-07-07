#!/usr/bin/env python3
"""
检测当前 B 站账号的收藏夹列表，并更新 bilibili-export-config.json。

行为：
- 读取现有的 bilibili-export-config.json（如果存在）。
- 调用 `bili favorites --json` 获取所有收藏夹。
- 合并结果：保留已有配置，新增收藏夹默认 enabled=false、target_wiki=""。
- 写回配置文件并打印摘要。

用法：
    python detect-folders.py
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
CONFIG_FILE = ROOT / "bilibili-export-config.json"


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_bili(args: list, timeout: int = 120) -> dict:
    cmd = ["bili"] + args + ["--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(result.stdout)


def extract_list(data, keys=None):
    if data is None:
        return None
    if isinstance(data, list):
        return data
    keys = keys or ["items", "data", "list", "medias"]
    for key in keys:
        if key in data:
            value = data[key]
            if isinstance(value, list):
                return value
            deeper = extract_list(value, keys)
            if deeper:
                return deeper
    return None


def list_favorite_folders() -> list:
    data = run_bili(["favorites"], timeout=60)
    folders = extract_list(data)
    if folders is None:
        raise RuntimeError("无法解析收藏夹列表")
    return folders


def main():
    print("🔍 检测 B 站收藏夹...")
    folders = list_favorite_folders()
    print(f"   发现 {len(folders)} 个收藏夹\n")

    config = load_json(CONFIG_FILE, {"folders": []})
    existing = {str(f.get("id", "")): f for f in config.get("folders", [])}

    merged = []
    for folder in folders:
        fid = str(folder.get("id", ""))
        name = folder.get("title", folder.get("name", "未命名"))
        if fid in existing:
            entry = existing[fid]
            # 保证新字段存在，保留已有 source/urls_file 值
            entry.setdefault("name", name)
            entry.setdefault("target_wiki", "")
            entry.setdefault("enabled", False)
            entry.setdefault("source", "favorites")
            entry.setdefault("urls_file", "")
            merged.append(entry)
            print(f"  [保留] {name} (id={fid}, enabled={entry.get('enabled')}, target_wiki='{entry.get('target_wiki')}', source='{entry.get('source')}')")
        else:
            entry = {
                "id": fid,
                "name": name,
                "target_wiki": "",
                "enabled": False,
                "source": "favorites",
                "urls_file": "",
            }
            merged.append(entry)
            print(f"  [新增] {name} (id={fid}, enabled=false, target_wiki='', source='favorites')")

    config["folders"] = merged
    if "_comment" not in config:
        config["_comment"] = "bilibili-export-config.json：配置需要自动转录的 B 站收藏夹。id/name 必填，target_wiki 留空表示不进映射直接到 Unmapped，enabled 为 false 表示跳过该收藏夹。"

    save_json(CONFIG_FILE, config)
    print(f"\n✅ 已更新：{CONFIG_FILE}")
    print(f"   共 {len(merged)} 个收藏夹")


if __name__ == "__main__":
    main()
