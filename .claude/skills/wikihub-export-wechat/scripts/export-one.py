#!/usr/bin/env python3
"""
单链接导出微信公众号文章。

用法：
    python export-one.py --url "https://mp.weixin.qq.com/s/xxxxx"

行为：
1. 读取项目根目录的 wechat-export-config.json（如果存在）获取 target_wiki 等配置。
2. 如果配置不存在或没有 enabled=true 的 folder，仍然继续运行，但会给出明确提示。
3. 使用 fetch_article.py 抓取文章。
4. 生成 markdown 到 target_wiki 指定目录，或默认到 Unmapped/。
5. 写入 wikihub-exported.json，去重键为 wechat_<article_id>。
6. 追加 pending item 到 /tmp/wikihub-pending.json。
"""

import argparse
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_article


# 通过 importlib 导入带连字符文件名的批量脚本，复用其中的工具函数。
_BATCH_SCRIPT_PATH = Path(__file__).resolve().parent / "export-wechat.py"
_spec = importlib.util.spec_from_file_location("export_wechat_batch", _BATCH_SCRIPT_PATH)
export_wechat_batch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export_wechat_batch)


ROOT = Path.cwd()
CONFIG_FILE = ROOT / "wechat-export-config.json"
EXPORTED_FILE = ROOT / "wikihub-exported.json"
UNMAPPED_DIR = ROOT / "Unmapped"
PENDING_FILE = Path("/tmp/wikihub-pending.json")


def load_enabled_folder():
    """返回第一个 enabled=true 的 folder 配置；缺失/禁用/异常时返回 None 并打印提示。"""
    if not CONFIG_FILE.exists():
        print(f"⚠️  未找到配置文件 {CONFIG_FILE}，将导出到 Unmapped/。", file=sys.stderr)
        return None

    try:
        config = export_wechat_batch.load_json(CONFIG_FILE, {"folders": []})
    except Exception as e:
        print(f"⚠️  读取 {CONFIG_FILE} 失败：{e}，将导出到 Unmapped/。", file=sys.stderr)
        return None

    folders = config.get("folders", [])
    enabled = [f for f in folders if f.get("enabled") is not False]

    if not enabled:
        print(f"⚠️  {CONFIG_FILE} 中没有 enabled=true 的 folder，将导出到 Unmapped/。", file=sys.stderr)
        return None

    return enabled[0]


def main():
    parser = argparse.ArgumentParser(description="单链接导出微信公众号文章")
    parser.add_argument("--url", required=True, help="微信公众号文章链接，如 https://mp.weixin.qq.com/s/...")
    args = parser.parse_args()

    url = (args.url or "").strip()
    if not url:
        print("错误：--url 不能为空", file=sys.stderr)
        sys.exit(1)

    article_id = fetch_article.extract_article_id(url)
    if not article_id:
        print(f"错误：无法从 URL 提取 article_id：{url}", file=sys.stderr)
        sys.exit(1)

    exported_key = f"wechat_{article_id}"
    exported = export_wechat_batch.load_json(EXPORTED_FILE, {})

    if exported_key in exported:
        existing = exported[exported_key]
        print(f"⏭️  {exported_key} 已在 wikihub-exported.json 中，跳过。")
        print(f"   文件路径：{existing.get('path', '')}")
        print(f"   去重键：{exported_key}")
        sys.exit(0)

    folder_cfg = load_enabled_folder()
    folder_name = folder_cfg.get("name", "单链接导出") if folder_cfg else "单链接导出"
    target_wiki = folder_cfg.get("target_wiki", "") if folder_cfg else ""

    target_dir = ROOT / target_wiki if target_wiki else UNMAPPED_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        data = fetch_article.fetch_article(url)
    except Exception as e:
        print(f"❌ 抓取失败：{e}", file=sys.stderr)
        sys.exit(1)

    if not data:
        print("❌ 抓取失败：未获取到有效文章数据", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    title = data.get("title") or article_id
    filename = export_wechat_batch.slugify(title) + ".md"
    file_path = export_wechat_batch.unique_path(target_dir, filename)
    rel_path = str(file_path.relative_to(ROOT))

    frontmatter = export_wechat_batch.build_frontmatter(data, folder_name, now)
    body = export_wechat_batch.build_body(data)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(frontmatter + body)

    exported[exported_key] = {
        "title": title,
        "path": rel_path,
        "exported_at": now,
        "source": "wechat",
        "folder": folder_name,
    }
    export_wechat_batch.save_json(EXPORTED_FILE, exported)

    snippet = (data.get("content") or title or "")[:2000]
    pending_items = export_wechat_batch.load_json(PENDING_FILE, [])
    pending_items.append({
        "card_id": exported_key,
        "title": title,
        "url": data.get("url", url),
        "path": rel_path,
        "snippet": snippet,
    })
    export_wechat_batch.save_json(PENDING_FILE, pending_items)

    print(f"✅ 已导出：{rel_path}")
    print(f"   去重键：{exported_key}")


if __name__ == "__main__":
    main()
