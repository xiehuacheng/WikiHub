---
name: podcast-fetcher
description: >
  通用播客单集获取工具。支持 Apple Podcasts show/episode 链接与 RSS feed URL，
  下载音频并为每集生成 Markdown 元数据文件。不依赖 WikiHub，可被任意工作流复用。
metadata:
  version: "1.0.0"
  author: orange
  tags: "podcast, rss, apple-podcasts, audio, fetch, generic-tool"
  triggers: "fetch podcast, 获取播客, podcast-fetcher"
---

# podcast-fetcher

`podcast-fetcher` 是一个**通用工具 skill**，只负责从 Apple Podcasts 或 RSS 获取播客单集信息、下载音频、生成 Markdown 元数据文件。它**不读取/写入任何 WikiHub 专属文件**（如 `wikihub-exported.json`、`*-export-config.json`、`*-pending.json` 等），也不执行 ASR 转录，因此可被任何需要播客内容的工作流复用。

## 前置条件

- Python 3.9+
- 系统已安装 `curl`
- 网络可访问 Apple Podcasts / iTunes Search API / RSS feed / 音频直链

## 安装

本 skill 仅使用 Python 标准库，无需安装额外依赖：

```bash
# requirements.txt 为空，仅作声明
python3 -m py_compile .claude/skills/podcast-fetcher/scripts/fetch.py
```

## CLI 用法

```bash
python3 .claude/skills/podcast-fetcher/scripts/fetch.py \
  --url "URL" \
  --output-dir "DIR" \
  [--latest N]
```

参数说明：

- `--url`：必填。支持以下三种 URL 类型：
  - Apple Podcasts 节目页（show）：`https://podcasts.apple.com/.../id<show_id>`
  - Apple Podcasts 单集页（episode）：`https://podcasts.apple.com/.../id<show_id>?i=<episode_id>`
  - RSS feed URL：以 `.xml` / `.rss` 结尾，或路径包含 `/feed` / `/rss`
- `--output-dir`：必填。音频和 Markdown 文件的输出目录。
- `--latest`：可选。show / RSS 链接时导出最新 N 集，默认 `1`。episode 链接忽略此参数。

### 示例

```bash
# Apple Podcasts show：导出最新 1 集
python3 .claude/skills/podcast-fetcher/scripts/fetch.py \
  --url "https://podcasts.apple.com/cn/podcast/id123456789" \
  --output-dir ./output

# Apple Podcasts show：导出最新 3 集
python3 .claude/skills/podcast-fetcher/scripts/fetch.py \
  --url "https://podcasts.apple.com/cn/podcast/id123456789" \
  --output-dir ./output \
  --latest 3

# Apple Podcasts episode：只导出该单集
python3 .claude/skills/podcast-fetcher/scripts/fetch.py \
  --url "https://podcasts.apple.com/cn/podcast/id123456789?i=987654321" \
  --output-dir ./output

# RSS feed：导出最新 2 集
python3 .claude/skills/podcast-fetcher/scripts/fetch.py \
  --url "https://example.com/podcast/feed.xml" \
  --output-dir ./output \
  --latest 2
```

## 行为

1. 识别 URL 类型（Apple show / Apple episode / RSS）。
2. Apple Podcasts 链接通过 iTunes Search API 获取 RSS feed URL。
3. 解析 RSS，提取每集标题、链接、enclosure 音频 URL、时长、作者、集数。
4. show / RSS 链接：按发布时间顺序取最新 N 集。
5. episode 链接：抓取 Apple 页面标题，在 RSS 中按标题精确匹配；匹配失败则回退到最新 1 集，并在 stderr 提示。
6. 对每集：
   - 使用 `curl` 下载音频到 `--output-dir`。
   - 生成 Markdown 文件，包含通用 frontmatter 与音频路径占位符。
7. stdout 输出 JSON 数组。

## 输出格式

### stdout

成功时输出 JSON 数组，每个元素对应一集：

```json
[
  {
    "success": true,
    "file": "/abs/path/to/output/episode-title.md",
    "title": "Episode Title",
    "url": "https://podcasts.apple.com/...",
    "author": "Show Author",
    "media_files": ["/abs/path/to/output/episode-title.m4a"],
    "metadata": {
      "duration": "01:23:45",
      "episode_id": "rss_42_a1b2c3d4"
    }
  }
]
```

字段说明：

- `success`：是否成功。
- `file`：生成的 Markdown 文件绝对路径。
- `title` / `url` / `author`：单集元数据。
- `media_files`：下载的音频文件绝对路径列表。
- `metadata.duration`：RSS 中的时长字符串（HH:MM:SS 或 MM:SS）。
- `metadata.episode_id`：稳定的单集 ID，规则见下。

若某一集失败，对应元素为：

```json
{
  "success": false,
  "title": "...",
  "url": "...",
  "error": "错误信息"
}
```

只要有任何一集失败，进程退出码为非零。

### 生成的 Markdown 文件

```markdown
---
title: "Episode Title"
url: "https://podcasts.apple.com/..."
author: "Show Author"
duration: "01:23:45"
fetched_at: "2026-07-07T04:13:32+00:00"
---

# Episode Title

[节目链接](https://podcasts.apple.com/...)

<!-- audio: ./episode-title.m4a -->
```

音频占位符使用相对于 Markdown 文件的路径 `./<filename>`，方便后续工作流将音频与 Markdown 一起移动。

## 稳定 ID 规则

- RSS 场景：`rss_<episode_num>_<hash(audio_url)>`
- 页面抓取场景：`url_<hash(audio_url)>`

`hash(audio_url)` 取音频 URL 的 SHA-256 前 8 位十六进制字符。

## 音频解析优先级

对于非直链页面（如单个节目页），按以下优先级提取音频 URL：

1. `<meta property/name="og:audio" content="...">`
2. `<audio src="...">`
3. `<audio><source src="...">`
4. 页面内联 JSON 中的 `enclosure` / `url` 字段
5. 页面中任意 `.mp3` / `.m4a` / `.wav` / `.ogg` / `.aac` 直链

## 注意事项

- 本 skill **不调用 ASR 转录**；需要文字稿时请配合 `transcribe-audio` 等工具使用。
- 本 skill **不读取 `podcast-export-config.json`**。
- 本 skill **不写入 `wikihub-exported.json` 或 `pending.json`**。
- 失败时会在 stderr 输出错误信息，并返回非零退出码。
