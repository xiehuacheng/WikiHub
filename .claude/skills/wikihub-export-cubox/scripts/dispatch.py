#!/usr/bin/env python3
"""
Cubox Dispatcher：从 Cubox 拉取未处理卡片，按链接域名自动分发到对应 skill 的 export-one.py，
导出成功后把卡片移动到归档文件夹。

用法：
    python dispatch.py
    python dispatch.py --folder "待读/技术"
    python dispatch.py --dry-run
    python dispatch.py --archive-folder "WikiHub_已归档"
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# 项目根目录：.claude/skills/wikihub-export-cubox/scripts/dispatch.py
ROOT = Path(__file__).resolve().parents[4]
EXPORTED_FILE = ROOT / "wikihub-exported.json"
ARCHIVE_FOLDER_DEFAULT = "WikiHub_已归档"

SKILL_DIRS = {
    "wechat": ROOT / ".claude" / "skills" / "wikihub-export-wechat" / "scripts",
    "podcast": ROOT / ".claude" / "skills" / "wikihub-export-podcast" / "scripts",
    "bilibili": ROOT / ".claude" / "skills" / "wikihub-export-bilibili" / "scripts",
    "xiaohongshu": ROOT / ".claude" / "skills" / "wikihub-export-xiaohongshu" / "scripts",
}

DOMAIN_KIND_MAP = {
    "mp.weixin.qq.com": "wechat",
    "podcasts.apple.com": "podcast",
    "bilibili.com": "bilibili",
    "b23.tv": "bilibili",
    "xiaohongshu.com": "xiaohongshu",
}


class CuboxCliError(Exception):
    """cubox-cli 调用失败或返回非预期结果。"""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.message = message
        self.stderr = stderr


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def run_cubox(args: list[str]) -> dict | list:
    """调用 cubox-cli，默认以 json 格式输出。"""
    cmd = ["cubox-cli"] + args + ["-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        # 未认证时的常见提示
        if "auth" in stderr.lower() or "login" in stderr.lower() or "unauthorized" in stderr.lower():
            raise CuboxCliError("cubox-cli 未认证，请先运行：cubox-cli auth login", stderr)
        raise CuboxCliError(f"cubox-cli 调用失败：{' '.join(cmd)}\n{stderr}", stderr)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise CuboxCliError(f"无法解析 cubox-cli 输出：{e}", result.stderr)


def get_domain(url: str) -> str:
    """提取 URL 的 netloc，并移除 www. 前缀。"""
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def classify_url(url: str) -> str | None:
    """根据域名返回卡片类型；不支持的域名返回 None。"""
    domain = get_domain(url)
    return DOMAIN_KIND_MAP.get(domain)


def extract_wechat_article_id(url: str) -> str:
    """复制 fetch_article.extract_article_id 的核心逻辑，用于生成去重键。"""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    def _first(key: str) -> str | None:
        values = qs.get(key)
        return values[0] if values else None

    biz = _first("__biz")
    mid = _first("mid")
    idx = _first("idx")
    if biz and mid and idx:
        return f"{biz}_{mid}_{idx}"

    match = re.search(r"/s/([^/?#]+)", parsed.path)
    if match:
        return match.group(1)

    return re.sub(r"[^a-zA-Z0-9_-]", "_", f"{parsed.path}{parsed.query}").strip("_") or "unknown"


def extract_bvid(url: str) -> str | None:
    """从 bilibili.com URL 提取 BVID；不处理 b23.tv 短链（由 export-one.py 解析）。"""
    match = re.search(r"bilibili\.com/video/(BV[\w]+)", url)
    return match.group(1) if match else None


def extract_xhs_note_id(url: str) -> str | None:
    """从小红书 URL 提取 note_id。"""
    patterns = [
        r"xiaohongshu\.com/explore/([a-zA-Z0-9]+)",
        r"xhslink\.com/([a-zA-Z0-9]+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def extract_dedup_key(kind: str, url: str) -> str | None:
    """根据类型生成预期的 wikihub-exported.json 去重键。"""
    if kind == "wechat":
        return f"wechat_{extract_wechat_article_id(url)}"
    if kind == "bilibili":
        bvid = extract_bvid(url)
        return f"bilibili_{bvid}" if bvid else None
    if kind == "xiaohongshu":
        note_id = extract_xhs_note_id(url)
        return f"xhs_{note_id}" if note_id else None
    if kind == "podcast":
        # podcast 的 episode_id 需要从 RSS 反查，dispatcher 层面跳过键检查，改为 URL 匹配
        return None
    return None


def url_already_exported(url: str, exported: dict) -> bool:
    """检查 URL 是否已作为某个导出项的 url 字段存在。"""
    for value in exported.values():
        if isinstance(value, dict) and value.get("url") == url:
            return True
    return False


def is_duplicate(kind: str, url: str, exported: dict) -> bool:
    """判断卡片是否已经被导出。"""
    key = extract_dedup_key(kind, url)
    if key and key in exported:
        return True
    if kind == "podcast" and url_already_exported(url, exported):
        return True
    return False


def find_archive_folder(folders: list[dict], name: str) -> dict | None:
    """在文件夹列表中按 name / nested_name 查找归档文件夹。"""
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        candidates = [folder.get("nested_name"), folder.get("name")]
        if any(c == name for c in candidates if c):
            return folder
    return None


def folder_matches(folder: dict, query: str) -> bool:
    """按 nested_name 或 name 匹配用户指定的文件夹。"""
    for key in ("nested_name", "name"):
        value = folder.get(key)
        if value and value == query:
            return True
    return False


def filter_cards_by_folder(cards: list[dict], folder_query: str) -> list[dict]:
    """只保留指定文件夹中的卡片。"""
    return [c for c in cards if folder_matches(c.get("folder") or {}, folder_query)]


def exclude_archive_cards(cards: list[dict], archive_name: str) -> list[dict]:
    """排除位于归档文件夹中的卡片。"""
    result = []
    for card in cards:
        folder = card.get("folder") or {}
        names = {folder.get("nested_name"), folder.get("name")}
        if archive_name not in names:
            result.append(card)
    return result


def get_skill_python(skill_dir: Path) -> str:
    """返回 skill 虚拟环境中的 python，如果没有则回退到系统 python3。"""
    venv_python = skill_dir.parent / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python3"


def dispatch_card(card: dict, kind: str, dry_run: bool, archive_folder_name: str) -> tuple[bool, str]:
    """调用对应 skill 的 export-one.py，成功后移动卡片到归档文件夹。"""
    card_id = str(card.get("id", ""))
    url = card.get("url", "")
    title = card.get("title") or "untitled"
    skill_dir = SKILL_DIRS[kind]
    export_script = skill_dir / "export-one.py"

    if dry_run:
        return True, "dry-run：跳过导出"

    python_exe = get_skill_python(skill_dir)
    result = subprocess.run(
        [python_exe, str(export_script), "--url", url],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        reason = stderr or stdout or f"export-one.py 返回非零退出码 {result.returncode}"
        return False, reason

    # 导出成功，移动卡片到归档文件夹
    move_result = subprocess.run(
        ["cubox-cli", "update", "--id", card_id, "--folder", archive_folder_name],
        capture_output=True,
        text=True,
    )
    if move_result.returncode != 0:
        stderr = move_result.stderr.strip()
        stdout = move_result.stdout.strip()
        return False, f"导出成功，但移动卡片失败：{stderr or stdout or 'cubox-cli update 返回非零'}"

    return True, "success"


def parse_args():
    parser = argparse.ArgumentParser(description="Cubox Dispatcher：按域名分发卡片到对应 skill 导出")
    parser.add_argument(
        "--folder",
        default="",
        help="只扫描指定 Cubox 文件夹（按 nested_name 匹配，fallback 到 name）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览会处理哪些卡片，不实际调用导出和移动",
    )
    parser.add_argument(
        "--archive-folder",
        default=ARCHIVE_FOLDER_DEFAULT,
        help=f"归档目标文件夹名称（默认：{ARCHIVE_FOLDER_DEFAULT}）",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    archive_folder_name = args.archive_folder or ARCHIVE_FOLDER_DEFAULT

    # 确保在 WikiHub 根目录
    if not EXPORTED_FILE.parent.exists():
        print(f"错误：无法定位项目根目录 {ROOT}", file=sys.stderr)
        sys.exit(1)

    # 1. 获取 Cubox 文件夹列表
    try:
        folders = run_cubox(["folder", "list"])
    except CuboxCliError as e:
        print(f"❌ {e.message}", file=sys.stderr)
        if e.stderr:
            print(f"   详细错误：{e.stderr}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(folders, list):
        print(f"错误：cubox-cli folder list 返回非列表类型：{type(folders)}", file=sys.stderr)
        sys.exit(1)

    # 2. 确认归档文件夹
    archive_folder = find_archive_folder(folders, archive_folder_name)
    if archive_folder is None:
        msg = f'未找到归档文件夹 "{archive_folder_name}"，请在 Cubox 中手动创建后再运行。'
        if args.dry_run:
            print(f"⚠️  dry-run：{msg}")
        else:
            print(f"❌ {msg}", file=sys.stderr)
            sys.exit(1)


    # 3. 获取卡片列表
    try:
        cards = run_cubox(["card", "list", "--all"])
    except CuboxCliError as e:
        print(f"❌ {e.message}", file=sys.stderr)
        if e.stderr:
            print(f"   详细错误：{e.stderr}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(cards, list):
        print(f"错误：cubox-cli card list 返回非列表类型：{type(cards)}", file=sys.stderr)
        sys.exit(1)

    total_cards = len(cards)
    cards = exclude_archive_cards(cards, archive_folder_name)
    if args.folder:
        cards = filter_cards_by_folder(cards, args.folder)

    exported = load_json(EXPORTED_FILE, {})

    # 4. 按域名分类并统计
    classified: dict[str, list[dict]] = {kind: [] for kind in SKILL_DIRS}
    classified["other"] = []
    skipped_duplicate = []

    for card in cards:
        url = card.get("url", "")
        kind = classify_url(url)
        if kind is None:
            classified["other"].append(card)
            continue
        if is_duplicate(kind, url, exported):
            skipped_duplicate.append((card, kind))
            continue
        classified[kind].append(card)

    # 5. 打印预览
    mode_label = "【dry-run 预览】" if args.dry_run else ""
    print(f"\n{mode_label}Cubox Dispatcher 汇总")
    print(f"  扫描卡片总数：{total_cards}")
    print(f"  排除归档后待处理：{len(cards)}")
    if args.folder:
        print(f"  限定文件夹：{args.folder}")
    print(f"  归档文件夹：{archive_folder_name}")
    print("\n按域名分类：")
    for kind in list(SKILL_DIRS.keys()) + ["other"]:
        count = len(classified[kind])
        dup_count = sum(1 for _, k in skipped_duplicate if k == kind) if kind != "other" else 0
        dup_info = f"（含已导出 {dup_count} 张）" if dup_count else ""
        print(f"  - {kind}: {count} 张{dup_info}")

    if skipped_duplicate:
        print(f"\n以下 {len(skipped_duplicate)} 张卡片已在 wikihub-exported.json 中，将跳过：")
        for card, kind in skipped_duplicate:
            print(f"  [{kind}] {card.get('title', '')} - {card.get('url', '')}")

    if args.dry_run:
        print("\n【dry-run】以下卡片将被处理：")
        for kind, items in classified.items():
            if kind == "other" or not items:
                continue
            for card in items:
                print(f"  [{kind}] {card.get('title', '')} - {card.get('url', '')}")
        if classified["other"]:
            print(f"\n【dry-run】以下 {len(classified['other'])} 张卡片域名不支持，将被跳过：")
            for card in classified["other"]:
                print(f"  [other] {card.get('title', '')} - {card.get('url', '')}")
        print("\ndry-run 结束，未执行任何导出或移动操作。")
        return

    # 6. 实际分发导出
    print("\n开始分发导出...")
    stats = {kind: {"success": 0, "failed": 0} for kind in SKILL_DIRS}
    stats["skipped_duplicate"] = len(skipped_duplicate)
    failed_items = []

    for kind in SKILL_DIRS:
        items = classified[kind]
        if not items:
            continue
        print(f"\n▶ {kind}：{len(items)} 张")
        for idx, card in enumerate(items, 1):
            title = card.get("title") or "untitled"
            print(f"  [{idx}/{len(items)}] {title}")
            success, reason = dispatch_card(card, kind, dry_run=False, archive_folder_name=archive_folder_name)
            if success:
                stats[kind]["success"] += 1
                print(f"    ✅ {reason}")
            else:
                stats[kind]["failed"] += 1
                failed_items.append((card, kind, reason))
                print(f"    ❌ {reason}", file=sys.stderr)

    # 7. 最终汇总
    total_success = sum(s["success"] for s in stats.values() if isinstance(s, dict))
    total_failed = sum(s["failed"] for s in stats.values() if isinstance(s, dict))

    print("\n============================")
    print("Cubox Dispatcher 完成")
    print(f"  扫描总数：{total_cards}")
    print(f"  已跳过（重复）：{stats['skipped_duplicate']}")
    print(f"  不支持域名：{len(classified['other'])}")
    print(f"  成功：{total_success}")
    print(f"  失败：{total_failed}")
    for kind in SKILL_DIRS:
        s = stats[kind]
        print(f"    - {kind}: 成功 {s['success']}，失败 {s['failed']}")

    if failed_items:
        print("\n失败明细：")
        for card, kind, reason in failed_items:
            print(f"  [{kind}] {card.get('url', '')}")
            print(f"    原因：{reason}")

    if total_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
