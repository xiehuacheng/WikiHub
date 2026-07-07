#!/usr/bin/env python3
"""
WikiHub 主控编排器。

负责从 Cubox 或输入队列获取待导入条目，按域名路由到通用工具 skill，
统一生成 WikiHub Markdown，并维护 WikiHub 状态文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml


ROOT = Path.cwd()

SKILL_DIRS = {
    "wechat": ROOT / ".claude" / "skills" / "wechat-fetcher" / "scripts",
    "podcast": ROOT / ".claude" / "skills" / "podcast-fetcher" / "scripts",
    "bilibili": ROOT / ".claude" / "skills" / "bilibili-fetcher" / "scripts",
    "xiaohongshu": ROOT / ".claude" / "skills" / "xiaohongshu-fetcher" / "scripts",
    "web": ROOT / ".claude" / "skills" / "generic-web-fetcher" / "scripts",
    "cubox": ROOT / ".claude" / "skills" / "cubox-fetcher" / "scripts",
    "transcribe": ROOT / ".claude" / "skills" / "transcribe-audio" / "scripts",
}

SKILL_CONFIG = ROOT / ".claude" / "skills" / "wikihub-orchestrator" / "wikihub-orchestrator-config.json"
ROOT_CONFIG = ROOT / "wikihub-orchestrator-config.json"
DEFAULT_CONFIG = SKILL_CONFIG if SKILL_CONFIG.exists() else ROOT_CONFIG
EXPORTED_FILE = ROOT / "wikihub-exported.json"
PENDING_FILE = Path("/tmp/wikihub-pending.json")

SOURCE_TAGS = {
    "wechat": ["公众号"],
    "podcast": ["播客"],
    "bilibili": ["B站"],
    "xiaohongshu": ["小红书"],
    "web": ["网页"],
    "weread": ["微信读书"],
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_skill_python(skill_dir: Path) -> str:
    """返回 skill venv 中的 python（如果存在），否则返回系统 python3。"""
    venv_python = skill_dir.parent / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python3"


def classify_url(url: str) -> str | None:
    """根据域名返回来源类型。未知 HTTP(S) 域名返回 'web'。"""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        scheme = parsed.scheme.lower()
    except Exception:
        return None
    if netloc.startswith("www."):
        netloc = netloc[4:]

    if netloc == "mp.weixin.qq.com":
        return "wechat"
    if netloc == "podcasts.apple.com":
        return "podcast"
    if netloc in ("bilibili.com", "b23.tv") or netloc.endswith(".bilibili.com"):
        return "bilibili"
    if netloc in ("xiaohongshu.com", "xhslink.com") or netloc.endswith(".xiaohongshu.com"):
        return "xiaohongshu"
    if scheme in ("http", "https") and netloc:
        return "web"
    return None


def extract_dedup_key(kind: str, url: str, metadata: dict) -> str | None:
    """生成去重键。优先使用来源特定 ID，否则回退到 URL。"""
    metadata = metadata or {}
    if kind == "wechat":
        article_id = metadata.get("article_id")
        if article_id:
            return f"wechat_{article_id}"
    elif kind == "podcast":
        episode_id = metadata.get("episode_id")
        if episode_id:
            return f"podcast_{episode_id}"
    elif kind == "bilibili":
        bvid = metadata.get("bvid")
        if bvid:
            return f"bilibili_{bvid}"
    elif kind == "xiaohongshu":
        note_id = metadata.get("note_id")
        if note_id:
            return f"xhs_{note_id}"
    elif kind == "web":
        page_id = metadata.get("page_id")
        if page_id:
            return f"web_{page_id}"
        if url:
            return f"web_{hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]}"
    # fallback: URL
    return url if url else None


def slugify(text: str, max_bytes: int = 200) -> str:
    """将文本转换为合法文件名。"""
    if not text:
        text = "untitled"
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    text = re.sub(r"[\s\x00-\x1f]+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    if not text:
        text = "untitled"
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore").rsplit("-", 1)[0]
    return text


def unique_path(directory: Path, filename: str) -> Path:
    """如果文件已存在，生成唯一文件名。"""
    base = directory / filename
    if not base.exists():
        return base
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def escape_yaml(value: str) -> str:
    """对 YAML 双引号字符串中的特殊字符进行转义。"""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 Markdown 中的 YAML frontmatter，返回 (frontmatter_dict, body)。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        fm = {}
    body = parts[2].lstrip("\n")
    return fm, body


def build_wikihub_frontmatter(data: dict, source: str, now: str) -> str:
    """生成 WikiHub 风格的 frontmatter。"""
    title = str(data.get("title", ""))
    url = data.get("url", "")
    author = str(data.get("author", ""))
    fetched_at = data.get("fetched_at") or now
    tags = SOURCE_TAGS.get(source, [])
    lines = [
        "---",
        f'title: "{escape_yaml(title)}"',
        f'url: "{url}"',
        f'source: "{source}"',
        f'tags: {json.dumps(tags, ensure_ascii=False)}',
        "ai_tags: []",
        f'author: "{escape_yaml(author)}"',
        "archive: false",
        f'fetched_at: "{fetched_at}"',
        f'exported_at: "{now}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def append_pending(item: dict):
    """追加条目到 /tmp/wikihub-pending.json。"""
    pending = load_json(PENDING_FILE, [])
    if not isinstance(pending, list):
        pending = []
    pending.append(item)
    save_json(PENDING_FILE, pending)


def is_already_exported(exported: dict, dedup_key: str, url: str) -> bool:
    """检查是否已导出。"""
    if dedup_key and dedup_key in exported:
        return True
    if url:
        for record in exported.values():
            if record.get("url") == url:
                return True
    return False


# ---------------------------------------------------------------------------
# 输入获取
# ---------------------------------------------------------------------------


def load_queue(path: Path) -> list[dict]:
    """从 --queue 文件加载输入队列。"""
    data = load_json(path, [])
    if not isinstance(data, list):
        print(f"错误：队列文件 {path} 必须是 JSON 数组", file=sys.stderr)
        sys.exit(1)
    return data


def fetch_cubox_cards(config: dict, dry_run: bool) -> list[dict]:
    """调用 cubox-fetcher 获取未归档卡片列表。dry-run 模式下也获取列表以便预览。"""
    skill_dir = SKILL_DIRS["cubox"]
    python = get_skill_python(skill_dir)
    output_json = Path("/tmp/wikihub-cubox-cards.json")
    archive_folder = config.get("archive_folder", "WikiHub_已归档")

    cmd = [
        python,
        str(skill_dir / "fetch.py"),
        "--output-json", str(output_json),
        "--archive-folder", archive_folder,
    ]
    if dry_run:
        print("[dry-run] 调用 cubox-fetcher 获取卡片列表", file=sys.stderr)
    else:
        print(f"获取 Cubox 卡片: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"cubox-fetcher 失败：{result.stderr.strip()}")

    return load_json(output_json, [])


# ---------------------------------------------------------------------------
# Fetcher 调用
# ---------------------------------------------------------------------------


def run_fetcher(kind: str, url: str, output_dir: Path, dry_run: bool) -> list[dict]:
    """调用对应工具 skill 抓取内容，返回结果对象或结果数组。"""
    if dry_run:
        print(f"[dry-run] 将调用 {kind}-fetcher: {url}")
        return []

    skill_dir = SKILL_DIRS[kind]
    python = get_skill_python(skill_dir)
    cmd = [
        python,
        str(skill_dir / "fetch.py"),
        "--url", url,
        "--output-dir", str(output_dir),
    ]
    print(f"调用 {kind}-fetcher: {url}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)

    # 某些 fetcher 把日志打到 stderr，结果在 stdout
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)

    if result.returncode != 0:
        raise RuntimeError(f"{kind}-fetcher 失败：{result.stdout.strip()} {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"无法解析 {kind}-fetcher 输出：{e}")

    if kind == "podcast":
        if not isinstance(data, list):
            raise RuntimeError(f"{kind}-fetcher 返回非数组：{type(data).__name__}")
        return data

    if not isinstance(data, dict):
        raise RuntimeError(f"{kind}-fetcher 返回非对象：{type(data).__name__}")
    return [data]


def transcribe_audio(audio_path: Path, dry_run: bool) -> str:
    """调用 transcribe-audio 转录音频，返回文本。"""
    if dry_run:
        print(f"[dry-run] 将转录音频: {audio_path}")
        return ""

    skill_dir = SKILL_DIRS["transcribe"]
    python = get_skill_python(skill_dir)
    cmd = [
        python,
        str(skill_dir / "transcribe.py"),
        "--input", str(audio_path),
        "--language", "auto",
    ]
    print(f"转录音频: {audio_path}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"transcribe-audio 失败：{result.stderr.strip()}")
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Markdown 处理与状态更新
# ---------------------------------------------------------------------------


def copy_media_files(media_files: list[str], target_dir: Path) -> dict[str, str]:
    """复制媒体文件到目标目录，返回旧文件名 -> 新文件名的映射。"""
    rename_map: dict[str, str] = {}
    for src_str in media_files:
        src = Path(src_str)
        if not src.exists():
            print(f"警告：媒体文件不存在 {src}", file=sys.stderr)
            continue
        dst = unique_path(target_dir, src.name)
        shutil.copy2(str(src), str(dst))
        if dst.name != src.name:
            rename_map[src.name] = dst.name
    return rename_map


def relocate_markdown(
    fetcher_result: dict,
    source: str,
    target_dir: Path,
    now: str,
    dry_run: bool,
) -> Path | None:
    """读取 fetcher 生成的 Markdown，生成 WikiHub Markdown 并保存到目标目录。"""
    md_path = Path(fetcher_result["file"])
    if not md_path.exists():
        raise RuntimeError(f"Markdown 文件不存在：{md_path}")

    original_text = md_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(original_text)

    title = fetcher_result.get("title") or fm.get("title", "")
    url = fetcher_result.get("url") or fm.get("url", "")
    author = fetcher_result.get("author") or fm.get("author", "")
    fetched_at = fm.get("fetched_at") or now

    media_files = fetcher_result.get("media_files") or []
    rename_map = {}
    if media_files:
        if dry_run:
            print(f"[dry-run] 将复制 {len(media_files)} 个媒体文件到 {target_dir}")
        else:
            rename_map = copy_media_files(media_files, target_dir)

    # 更新 body 中的媒体引用
    for old_name, new_name in rename_map.items():
        body = re.sub(rf"\./{re.escape(old_name)}\b", f"./{new_name}", body)
        body = re.sub(rf"\b{re.escape(old_name)}\b", new_name, body)

    data = {
        "title": title,
        "url": url,
        "author": author,
        "fetched_at": fetched_at,
    }
    new_frontmatter = build_wikihub_frontmatter(data, source, now)
    new_text = new_frontmatter + body

    safe_title = slugify(str(title))
    target_filename = f"{safe_title}.md"
    target_path = unique_path(target_dir, target_filename)

    if dry_run:
        print(f"[dry-run] 将生成 Markdown: {target_path}")
        return target_path

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_text(new_text, encoding="utf-8")
    return target_path


def append_transcription(md_path: Path, text: str, dry_run: bool):
    """将转录文本追加到 Markdown 文件末尾。"""
    if not text:
        return
    if dry_run:
        print(f"[dry-run] 将追加转录到 {md_path}")
        return

    content = md_path.read_text(encoding="utf-8")
    transcription_section = f"\n\n## 转录\n\n{text}\n"
    md_path.write_text(content + transcription_section, encoding="utf-8")


def update_exported_state(
    exported: dict,
    dedup_key: str,
    title: str,
    url: str,
    source: str,
    target_path: Path,
    now: str,
):
    """更新 wikihub-exported.json 记录。"""
    rel_path = str(target_path.relative_to(ROOT))
    exported[dedup_key] = {
        "title": title,
        "url": url,
        "source": source,
        "path": rel_path,
        "exported_at": now,
        "ai_tags": [],
    }


def archive_cubox_card(card_id: str, archive_folder: str, dry_run: bool):
    """调用 cubox-cli 归档单张卡片。"""
    if not card_id:
        return
    if dry_run:
        print(f"[dry-run] 将归档 Cubox 卡片: {card_id} -> {archive_folder}")
        return

    cmd = ["cubox-cli", "update", "--id", card_id, "--folder", archive_folder]
    print(f"归档 Cubox 卡片: {card_id}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"cubox-cli 归档失败：{result.stderr.strip()}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def load_config(path: Path) -> dict:
    """加载 orchestrator 配置文件，缺失字段使用默认值。"""
    default = {
        "archive_folder": "WikiHub_已归档",
        "target_wiki": "",
        "sources": {
            "wechat": {"enabled": True},
            "podcast": {"enabled": True},
            "bilibili": {"enabled": True},
            "xiaohongshu": {"enabled": True},
            "web": {"enabled": False},
            "weread": {"enabled": False},
        },
    }
    config = load_json(path, default)
    for key, value in default.items():
        if key not in config:
            config[key] = value
    if "sources" not in config or not isinstance(config["sources"], dict):
        config["sources"] = default["sources"]
    for source, source_default in default["sources"].items():
        if source not in config["sources"]:
            config["sources"][source] = source_default
        if "enabled" not in config["sources"][source]:
            config["sources"][source]["enabled"] = source_default["enabled"]
    return config


def normalize_input_item(item: dict) -> dict:
    """统一输入条目格式。"""
    if not isinstance(item, dict):
        return {}
    return {
        "url": (item.get("url") or "").strip(),
        "title": (item.get("title") or "").strip(),
        "id": str(item.get("id", "")).strip(),
    }


def process_item(
    item: dict,
    config: dict,
    exported: dict,
    dry_run: bool,
) -> dict:
    """处理单个输入条目，返回结果统计。"""
    url = item["url"]
    title = item["title"]
    card_id = item["id"]
    result = {"status": "pending", "url": url, "error": None}

    if not url:
        result["status"] = "skipped"
        result["error"] = "缺少 URL"
        return result

    source = classify_url(url)
    if source is None:
        result["status"] = "skipped"
        result["error"] = f"未知域名: {url}"
        return result

    if not config["sources"].get(source, {}).get("enabled", False):
        result["status"] = "skipped"
        result["error"] = f"来源 {source} 未启用"
        return result

    if source == "weread":
        result["status"] = "skipped"
        result["error"] = "微信读书暂不支持"
        return result

    # 先调用 fetcher 以获取元数据，再生成去重键
    with tempfile.TemporaryDirectory(prefix="wikihub-fetch-", dir="/tmp") as tmp_dir:
        output_dir = Path(tmp_dir)
        try:
            fetcher_results = run_fetcher(source, url, output_dir, dry_run)
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            return result

        if dry_run:
            result["status"] = "dry_run"
            return result

        processed = 0
        for fetcher_result in fetcher_results:
            if not isinstance(fetcher_result, dict):
                continue
            if not fetcher_result.get("success"):
                error = fetcher_result.get("error", "未知错误")
                print(f"抓取失败 {url}: {error}", file=sys.stderr)
                continue

            metadata = fetcher_result.get("metadata") or {}
            dedup_key = extract_dedup_key(source, url, metadata)
            if not dedup_key:
                print(f"无法生成去重键: {url}", file=sys.stderr)
                continue

            if is_already_exported(exported, dedup_key, url):
                print(f"跳过已导出条目: {dedup_key}", file=sys.stderr)
                continue

            now = datetime.now(timezone.utc).isoformat()
            target_wiki = config.get("target_wiki", "").strip()
            target_dir = ROOT / target_wiki if target_wiki else ROOT / "Unmapped"

            try:
                target_path = relocate_markdown(fetcher_result, source, target_dir, now, dry_run=False)
            except Exception as e:
                print(f"生成 Markdown 失败 {url}: {e}", file=sys.stderr)
                continue

            if not target_path:
                continue

            # 转录音频
            media_files = fetcher_result.get("media_files") or []
            for media_str in media_files:
                media_path = Path(media_str)
                if not media_path.exists():
                    continue
                # 只转录音频文件
                if media_path.suffix.lower() not in (".m4a", ".mp3", ".aac", ".wav", ".flac", ".ogg"):
                    continue
                try:
                    transcript = transcribe_audio(media_path, dry_run=False)
                    append_transcription(target_path, transcript, dry_run=False)
                except Exception as e:
                    print(f"转录失败 {media_path}: {e}", file=sys.stderr)

            update_exported_state(
                exported,
                dedup_key,
                fetcher_result.get("title", title),
                fetcher_result.get("url", url),
                source,
                target_path,
                now,
            )

            append_pending({
                "card_id": dedup_key,
                "title": fetcher_result.get("title", title),
                "url": fetcher_result.get("url", url),
                "path": str(target_path.relative_to(ROOT)),
                "snippet": fetcher_result.get("title", title),
            })

            processed += 1

        if processed == 0:
            result["status"] = "skipped"
            result["error"] = "无有效结果"
        else:
            result["status"] = "success"
            result["count"] = processed

    # 归档 Cubox 卡片（仅在来源是 Cubox 且成功处理时）
    if card_id and result["status"] == "success":
        try:
            archive_cubox_card(card_id, config.get("archive_folder", "WikiHub_已归档"), dry_run)
        except Exception as e:
            print(f"归档 Cubox 卡片失败 {card_id}: {e}", file=sys.stderr)
            # 不归滚已导出的 Markdown

    return result


def print_report(results: list[dict]):
    """输出汇总报告。"""
    success = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "failed")
    skipped = sum(1 for r in results if r["status"] in ("skipped", "dry_run"))
    total = len(results)

    print("\n========== WikiHub 编排报告 ==========")
    print(f"总条目: {total}")
    print(f"成功: {success}")
    print(f"失败: {failed}")
    print(f"跳过: {skipped}")

    if failed:
        print("\n失败详情:")
        for r in results:
            if r["status"] == "failed":
                print(f"  - {r['url']}: {r['error']}")

    if skipped:
        print("\n跳过详情:")
        for r in results:
            if r["status"] == "skipped":
                print(f"  - {r['url']}: {r['error']}")


def main():
    parser = argparse.ArgumentParser(description="WikiHub 主控编排器")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际抓取和写文件")
    parser.add_argument("--queue", type=Path, help="输入队列 JSON 文件路径")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)
    exported = load_json(EXPORTED_FILE, {})
    if not isinstance(exported, dict):
        exported = {}

    # 获取输入
    if args.queue:
        input_items = load_queue(args.queue)
        print(f"从队列读取 {len(input_items)} 条输入", file=sys.stderr)
    else:
        try:
            input_items = fetch_cubox_cards(config, args.dry_run)
            print(f"从 Cubox 获取 {len(input_items)} 张卡片", file=sys.stderr)
        except Exception as e:
            print(f"获取 Cubox 卡片失败: {e}", file=sys.stderr)
            sys.exit(1)

    results = []
    for item in input_items:
        normalized = normalize_input_item(item)
        if not normalized["url"]:
            results.append({"status": "skipped", "url": "", "error": "缺少 URL"})
            continue
        result = process_item(normalized, config, exported, args.dry_run)
        results.append(result)

    # dry-run 不写状态文件
    if not args.dry_run:
        save_json(EXPORTED_FILE, exported)

    print_report(results)


if __name__ == "__main__":
    main()
