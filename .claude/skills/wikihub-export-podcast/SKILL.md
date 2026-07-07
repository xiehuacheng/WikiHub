---
name: wikihub-export-podcast
description: >
  导出播客节目为本地 Markdown source 文件。支持 RSS 订阅（自动解析 enclosure、itunes:duration、itunes:episode）
  以及单条 URL 抓取（自动提取 og:audio、<audio> 标签或内联 JSON 中的音频直链），转录后写入 Unmapped/
  或配置的 wiki raw 目录，并生成 /tmp/wikihub-pending.json 供后续 Agent 分类。
metadata:
  version: "1.0.0"
  author: orange
  tags: "podcast, export, transcription, rss, knowledge-management"
  triggers: "导出播客, 同步播客, podcast 导出, 转录播客"
---

# 播客导出 Skill

将播客节目批量转录为本地 Markdown source 文件，后续通过 `wikihub-export` skill 的分类管道进行打标签、隔离、迁移和看板生成。

## 前置要求

- 已安装转录依赖（在 skill 目录下创建 `.venv`）：
  ```bash
  cd .claude/skills/wikihub-export-podcast
  uv venv --python 3.12
  uv pip install -r requirements.txt
  ```
- 已配置阿里云环境变量：
  ```bash
  export DASHSCOPE_API_KEY="sk-..."
  export OSS_ACCESS_KEY_ID="..."
  export OSS_ACCESS_KEY_SECRET="..."
  export OSS_BUCKET="your-bucket-name"
  export OSS_ENDPOINT="oss-cn-guangzhou.aliyuncs.com"
  ```
  其中 `OSS_ENDPOINT` 需替换为 bucket 实际所在地域的 endpoint。
- 阿里云 OSS bucket 已创建，并已为 RAM 用户授权对 `your-bucket/wikihub-asr/*` 的 `PutObject`、`GetObject`、`DeleteObject` 权限。

## 配置

项目根目录 `podcast-export-config.json`：

```json
{
  "folders": [
    { "name": "播客 RSS 订阅", "source": "rss", "urls_file": "podcast-feeds.urls", "target_wiki": "", "enabled": false },
    { "name": "精选播客", "source": "urls", "urls_file": "podcast-selected.urls", "target_wiki": "", "enabled": true }
  ]
}
```

- `name`：来源名称，仅用于日志可读性。
- `source`：数据来源。
  - `rss`：读取 `urls_file` 中每行一个 RSS URL，解析 `<item>` 列表。
  - `urls`：读取 `urls_file` 中每行一个节目页面或直链 URL，自动提取音频。
- `urls_file`：指向项目根目录下的 `.urls` 文件。
- `target_wiki`：目标 wiki raw 目录。留空表示进入 `Unmapped/` 等 Agent 分类。
- `enabled`：`false` 表示跳过该来源。

### 自动检测配置

```bash
make detect-podcast-folders
```

会初始化 `podcast-export-config.json`，默认添加一个名为 "播客 RSS 订阅"、source=rss、默认 `enabled=false` 的 folder。

## 用法

```bash
# 1. 检测并配置来源（首次或配置有变化时）
make detect-podcast-folders

# 2. 编辑 podcast-feeds.urls / podcast-selected.urls，填入 RSS 或节目 URL

# 3. 导出并转录
make export-podcast
```

`make export-podcast` 会先扫描所有 `enabled: true` 的 folder，列出待转录的节目清单（来源、标题、episode ID、目标路径），并提示确认；确认后才会开始下载音频并转录。

### 直接导出指定 URL 列表

```bash
# 仅导出 podcast-selected.urls 中的节目（非交互）
python3 .claude/skills/wikihub-export-podcast/scripts/export-podcast.py \
  --urls-file podcast-selected.urls --yes
```

### 单链接导出

使用 `scripts/export-one.py` 直接导出单条 Apple Podcasts 或 RSS feed URL，无需编辑 `.urls` 文件。

```bash
# Apple Podcasts 节目页（show）：导出最新 1 集
python3 .claude/skills/wikihub-export-podcast/scripts/export-one.py \
  --url "https://podcasts.apple.com/cn/podcast/id123456789"

# Apple Podcasts 单集页（episode）：导出该单集
python3 .claude/skills/wikihub-export-podcast/scripts/export-one.py \
  --url "https://podcasts.apple.com/cn/podcast/id123456789?i=987654321"

# RSS feed：导出最新 1 集
python3 .claude/skills/wikihub-export-podcast/scripts/export-one.py \
  --url "https://example.com/podcast/feed.xml"

# show / RSS 链接可导出最新 N 集（episode 链接无效）
python3 .claude/skills/wikihub-export-podcast/scripts/export-one.py \
  --url "https://example.com/podcast/feed.xml" --latest 3
```

行为：

- Apple Podcasts show 链接：通过 iTunes Search API 获取 `feedUrl`，解析 RSS 后导出最新 `--latest` 集（默认 1）。
- Apple Podcasts episode 链接：抓取 Apple 页面获取单集标题，在 RSS 中按标题匹配；若匹配失败，默认导出最新 1 集并提示。
- RSS feed URL：直接解析并导出最新 `--latest` 集。
- 配置文件 `podcast-export-config.json` 不存在或全部禁用时，脚本仍会运行，并提示导出到 `Unmapped/`；否则使用第一个 `enabled: true` folder 的 `target_wiki`。
- 去重键与批量导出一致，为 `podcast_<episode_id>`，写入 `wikihub-exported.json`。
- 导出的 pending item 追加到 `/tmp/wikihub-pending.json`。

## 行为

1. 读取 `podcast-export-config.json`。
2. 对每个 `enabled: true` 的 folder：
   - `source == "rss"`：解析 RSS，提取每个 `<item>` 的标题、enclosure URL、时长、集数。
   - `source == "urls"`：读取 `urls_file` 中的 URL，抓取页面并提取音频直链与标题。
3. 跳过已在 `wikihub-exported.json` 中的节目（key 为 `podcast_<episode_id>`）。
4. 对未导出的节目：
   - 下载音频到本地临时目录。
   - 使用阿里云 **FunASR** 在线转录为文字稿（音频通过阿里云 OSS 临时中转，识别后自动删除）。
5. 生成 source markdown 文件：
   ```yaml
   ---
   podcast_episode_id: "rss_42_a1b2c3d4"
   title: "..."
   url: "https://www.xiaoyuzhoufm.com/episode/xxxxx"
   folder: "播客 RSS 订阅"
   tags: ["播客"]
   ai_tags: []
   author: "..."
   duration: "01:23:45"
   duration_seconds: 5025
   exported_at: "2026-07-04T12:00:00+00:00"
   ---
   ```
6. 生成 `/tmp/wikihub-pending.json`，其中 `snippet` 为文字稿前 2000 字，供 Agent 分类使用。

## 稳定 ID 规则

- RSS 场景：`rss_<episode_num>_<hash(audio_url)>`
- URL 场景：`url_<hash(audio_url)>`

其中 `hash(audio_url)` 取 URL 的 SHA-256 前 8 位十六进制字符，确保同一节目不因标题变化而重复导出。

## 音频解析优先级

页面抓取时按以下优先级提取音频 URL：

1. `<meta property/name="og:audio" content="...">`
2. `<audio src="...">`
3. 页面内联 JSON 中的 `audioUrl` / `mediaSrc` / `enclosure` / `url`
4. 页面中任意 `.mp3` / `.m4a` / `.wav` / `.ogg` / `.aac` 直链

## 转录脚本

本 skill 内置阿里云 FunASR + OSS 中转客户端：

- `asr_client/transcribe_audio()`：统一入口，转录本地音频文件。
- `scripts/download_audio.py`：RSS 解析、页面音频提取、音频下载。

## 后续流程

导出完成后，和 Cubox / B 站 / 小红书一样执行：

```bash
make all
```

Agent 会基于文字稿内容判断 quarantine 和 `ai_tags`，然后自动迁移、生成看板。

## 关联 skill

- [[wikihub-export]]：通用分类、迁移、看板生成
- [[wikihub-import-select]]：本地 Web 面板，人工选择要导出的收藏条目
- [[wikihub-export-cubox]]：Cubox 导出
- [[wikihub-export-bilibili]]：B 站收藏夹导出
- [[wikihub-export-xiaohongshu]]：小红书收藏夹导出
