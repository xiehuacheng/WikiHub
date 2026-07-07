# bilibili-fetcher

A generic, WikiHub-agnostic utility skill for fetching Bilibili video metadata
and audio. It can be reused by any workflow or project that needs to download a
Bilibili video's audio track and produce a Markdown file with generic frontmatter.

## What it does

- Accepts a Bilibili URL (`bilibili.com` or `b23.tv` short link).
- Resolves short links and extracts the BVID.
- Fetches video title and uploader (UP主) information.
- Downloads the video's audio track into the specified output directory.
- Writes a Markdown file with generic YAML frontmatter and an audio placeholder.
- Prints a JSON result to stdout.

## What it does NOT do

- It does **not** perform ASR/transcription. Use a separate transcribe-audio skill
  for that.
- It does **not** read or write any WikiHub-specific files such as
  `wikihub-exported.json`, `bilibili-export-config.json`, or `pending.json`.
- It does **not** manage export state or deduplication.

## Requirements

- Python 3.10+
- [bilibili-cli](https://github.com/luciddream-tsin/bilibili-cli) installed and
  available on `PATH` as `bili`.

This skill uses only the Python standard library, so `requirements.txt` is
intentionally empty. Install `bilibili-cli` via the method documented by that
project (for example, `pip install bilibili-cli`).

## Usage

```bash
# 单条视频抓取
python3 .claude/skills/bilibili-fetcher/scripts/fetch.py \
  --url "https://www.bilibili.com/video/BV1xx411c7mD" \
  --output-dir ./output

# 同步当前登录用户的收藏夹（需要 bilibili-export-config.json 指定启用哪些收藏夹）
python3 .claude/skills/bilibili-fetcher/scripts/sync-favorites.py \
  --config bilibili-export-config.json \
  --output-json /tmp/bili-favorites.json
```

Or with a short link:

```bash
python3 .claude/skills/bilibili-fetcher/scripts/fetch.py \
  --url "https://b23.tv/xxxxxx" \
  --output-dir ./output
```

### Output

Stdout contains a single JSON object:

```json
{
  "success": true,
  "file": "/abs/path/output/video-title.md",
  "title": "视频标题",
  "url": "https://www.bilibili.com/video/BV1xx411c7mD/",
  "author": "UP主名称",
  "media_files": ["/abs/path/output/video-title.m4a"],
  "metadata": {
    "bvid": "BV1xx411c7mD"
  }
}
```

On failure:

```json
{
  "success": false,
  "error": "错误信息",
  "url": "...",
  "file": null,
  "title": null,
  "author": null,
  "media_files": [],
  "metadata": {}
}
```

### Generated Markdown format

```markdown
---
title: "视频标题"
url: "https://www.bilibili.com/video/BV1xx411c7mD/"
author: "UP主"
fetched_at: "2026-01-01T00:00:00+00:00"
---

# 视频标题

[视频链接](https://www.bilibili.com/video/BV1xx411c7mD/)

<!-- audio: ./video-title.m4a -->
```

## Integration notes

Because this skill is stateless and WikiHub-agnostic, callers are responsible for:

- Providing a valid `--output-dir`.
- Handling deduplication if needed.
- Kicking off transcription as a separate step (the audio file path is returned in
  `media_files`).
