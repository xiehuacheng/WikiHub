#!/usr/bin/env python3
"""
使用 bilibili-cli 的已登录态下载音频，再用阿里云 FunASR 转录。

解决 yt-dlp 在部分网络环境下被 B 站 412 拦截的问题。

用法：
    python transcribe_one.py BV1bt421L7t1 ./output
    python transcribe_one.py BV1bt421L7t1 ./output --language zh

环境变量（必需）：
    DASHSCOPE_API_KEY
    OSS_ACCESS_KEY_ID
    OSS_ACCESS_KEY_SECRET
    OSS_BUCKET
    OSS_ENDPOINT
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# 让脚本无论从哪里启动都能导入 skill 根目录下的 asr_client
_SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

# 如果当前不是 skill venv 中的 Python，且 venv 存在，则自动切换到 venv 执行
_VENV_PYTHON = _SKILL_ROOT / ".venv" / "bin" / "python"
if _VENV_PYTHON.exists() and sys.executable != str(_VENV_PYTHON):
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), __file__] + sys.argv[1:])


def run_cmd(cmd: list, timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess:
    """运行命令并返回结果。"""
    print(f"[run] {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def extract_bvid(url: str) -> str:
    """从 URL 或纯 BV 号中提取 BV 号。"""
    m = re.search(r"(BV[\w]+)", url)
    if m:
        return m.group(1)
    raise ValueError(f"无法从输入中提取 BV 号：{url}")


def get_video_info(bvid: str) -> tuple:
    """通过 bilibili-cli 获取视频标题和 UP 主。"""
    try:
        result = run_cmd(["bili", "video", bvid, "--yaml"], timeout=60, check=False)
        if result.returncode != 0:
            return bvid, ""
        # 简单解析 YAML，只取 title 和 owner.name
        title = bvid
        uploader = ""
        for line in result.stdout.splitlines():
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip()
            if line.strip().startswith("name:") and not uploader:
                uploader = line.split(":", 1)[1].strip()
        return title or bvid, uploader
    except Exception:
        return bvid, ""


def download_audio_with_bili_cli(bvid: str, tmpdir: str) -> str:
    """使用 bilibili-cli 下载完整音频。返回音频文件路径。"""
    print("  ⬇️  使用 bilibili-cli 下载音频...", file=sys.stderr)

    # bilibili-cli 默认输出：/tmpdir/{title}/{title}.m4a
    output_dir = os.path.join(tmpdir, "audio")
    os.makedirs(output_dir, exist_ok=True)

    run_cmd(
        ["bili", "audio", bvid, "--no-split", "-o", output_dir],
        timeout=300,
    )

    # 找到下载的音频文件
    audio_exts = (".m4a", ".mp3", ".aac", ".wav", ".flac", ".ogg")
    files = []
    for ext in audio_exts:
        files.extend(Path(output_dir).rglob(f"*{ext}"))

    if not files:
        raise FileNotFoundError(f"未在 {output_dir} 找到下载的音频文件")

    # 取最大的音频文件（避免可能的临时文件）
    audio_path = str(max(files, key=lambda p: p.stat().st_size))
    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    print(f"  ✅ 音频：{audio_path} ({size_mb:.1f} MB)", file=sys.stderr)
    return audio_path


def transcribe_audio(audio_path: str, language: str = "auto") -> str:
    """使用阿里云 FunASR 转录音频（OSS 中转）。"""
    from asr_client import transcribe_audio as asr_transcribe

    print("  🎙️  提交阿里云 FunASR 识别...", file=sys.stderr)
    text = asr_transcribe(audio_path, language=language)
    print("  ✅ 识别完成", file=sys.stderr)
    return text


def transcribe_bvid(bvid: str, language: str = "auto") -> tuple:
    """转录单个 B 站视频，返回 (title, uploader, text)。"""
    print("=" * 50, file=sys.stderr)
    print("Step 1: 获取视频信息...", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    title, uploader = get_video_info(bvid)
    print(f"  📺 {title}  | UP: {uploader or '未知'}", file=sys.stderr)

    tmpdir = tempfile.mkdtemp(prefix="bili-collect2md-")
    try:
        print("\n" + "=" * 50, file=sys.stderr)
        print("Step 2: 下载音频...", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        audio_path = download_audio_with_bili_cli(bvid, tmpdir)

        print("\n" + "=" * 50, file=sys.stderr)
        print("Step 3: 转录...", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        text = transcribe_audio(audio_path, language)

        print("\n✅ Done!", file=sys.stderr)
        print(f"  字数：{len(text)}", file=sys.stderr)
        return title, uploader, text
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def build_markdown(title: str, text: str, bvid: str, uploader: str) -> str:
    """生成带 frontmatter 的 Markdown。"""
    now = datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.bilibili.com/video/{bvid}/"
    safe_title = "".join(c for c in title if c.isalnum() or c in "-_ 《》").strip()[:50]
    return f"""---
title: {title}
type: note
platform: bilibili
source: {url}
author: {uploader}
created: {now}
tags: [B站]
language: zh
transcriber: fun-asr
---

# {title}

{text}
""", safe_title


def main():
    parser = argparse.ArgumentParser(description="B 站视频转录（使用 bilibili-cli 已登录态下载音频）")
    parser.add_argument("bvid", help="B 站视频 BV 号或链接")
    parser.add_argument("output", nargs="?", default=".", help="输出目录")
    parser.add_argument("--output", "-o", dest="output_opt", help="输出目录")
    parser.add_argument("--language", default="auto", help="识别语言，默认 auto")
    args = parser.parse_args()

    output_dir = args.output_opt or args.output
    bvid = extract_bvid(args.bvid)
    title, uploader, text = transcribe_bvid(bvid, args.language)

    markdown, safe_title = build_markdown(title, text, bvid, uploader)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{safe_title or bvid}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"  Output: {output_path}", file=sys.stderr)
    print(output_path)


if __name__ == "__main__":
    main()
