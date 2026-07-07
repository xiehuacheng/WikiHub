---
name: wikihub-export-bilibili
description: >
  登录 B 站账号，读取配置的收藏夹，自动转录未转录的视频为 Markdown source 文件。
  写入 Unmapped/ 或配置的 wiki raw 目录，并生成 /tmp/wikihub-pending.json 供后续 Agent 分类。
metadata:
  version: "1.0.0"
  author: orange
  tags: "bilibili, export, transcription, knowledge-management"
  triggers: "导出 B 站收藏夹, 同步 bilibili 收藏夹, B 站收藏夹转录"
---

# B 站收藏夹导出 Skill

将 B 站收藏夹视频批量转录为本地 Markdown source 文件，后续通过 `wikihub-export` skill 的分类管道进行打标签、隔离、迁移和看板生成。

## 前置要求

- 已安装并登录 `bilibili-cli`：
  ```bash
  uv tool install bilibili-cli
  bili login
  ```
- 已创建 `bilibili-export-config.json` 配置要处理的收藏夹。
- 已安装转录依赖（在 `.venv` 中）：
  ```bash
  cd .claude/skills/wikihub-export-bilibili
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

项目根目录 `bilibili-export-config.json`：

```json
{
  "folders": [
    { "id": "3401008874", "name": "垃圾佬装机", "source": "favorites", "urls_file": "", "target_wiki": "Tech_wiki/00-Raw", "enabled": true },
    { "id": "3689760674", "name": "自我提升", "source": "favorites", "urls_file": "", "target_wiki": "", "enabled": true },
    { "name": "精选视频", "source": "urls", "urls_file": "bilibili-selected.urls", "target_wiki": "", "enabled": true }
  ]
}
```

- `id`：收藏夹 ID。`source` 为 `favorites` 时必填。
- `name`：收藏夹名称，仅用于日志可读性。
- `source`：数据来源。
  - `favorites`：调用 `bili favorites <FAV_ID> --json` 获取视频列表。
  - `urls`：读取 `urls_file` 中每行一个 B 站 URL 或 BV 号。
- `urls_file`：当 `source` 为 `urls` 时必填，指向项目根目录下的 `.urls` 文件。
- `target_wiki`：目标 wiki raw 目录。留空表示进入 `Unmapped/` 等 Agent 分类。
- `enabled`：`false` 表示跳过该收藏夹。

### 自动检测收藏夹

```bash
make detect-bilibili-folders
```

会读取当前 B 站账号的所有收藏夹，合并到 `bilibili-export-config.json`，新增的收藏夹默认 `enabled: false`、`target_wiki: ""`。

## 用法

```bash
# 1. 检测并配置收藏夹（首次或收藏夹有变化时）
make detect-bilibili-folders

# 2. 通过选择面板人工筛选（推荐）
make select-bilibili

# 3. 导出并转录
make export-bilibili
```

`make export-bilibili` 会先扫描所有 `enabled: true` 的收藏夹，列出待转录的视频清单（收藏夹、标题、BVID、目标路径），并提示确认；确认后才会开始下载音频并转录。

### 直接导出指定 URL 列表

```bash
# 仅导出 bilibili-selected.urls 中的视频（非交互）
python3 .claude/skills/wikihub-export-bilibili/scripts/export-bilibili.py \
  --urls-file bilibili-selected.urls --yes
```

## 行为

1. 读取 `bilibili-export-config.json`。
2. 对每个 `enabled: true` 的收藏夹，调用 `bili favorites <FAV_ID> --json` 获取视频列表。
3. 跳过已在 `wikihub-exported.json` 中的 `bvid`（避免重复转录）。
4. 对未转录的视频：
   - 使用 `bilibili-cli` 已登录态下载音频（避免 yt-dlp 412 问题）。
   - 使用阿里云 **FunASR** 在线转录为文字稿（音频通过阿里云 OSS 临时中转，识别后自动删除）。
5. 生成 source markdown 文件：
   ```yaml
   ---
   bilibili_bvid: "BV1bt421L7t1"
   title: "..."
   url: "https://www.bilibili.com/video/BV1bt421L7t1/"
   folder: "垃圾佬装机"
   tags: []
   ai_tags: []
   duration: "09:22"
   duration_seconds: 562
   author: "IT豪哥"
   synced_at: "..."
   ---
   ```
6. 生成 `/tmp/wikihub-pending.json`，其中 `snippet` 为文字稿前 2000 字，供 Agent 分类使用。

## 转录脚本

本 skill 内置转录能力：

- `scripts/transcribe_one.py`：转录单个 B 站视频并输出 Markdown。
- `scripts/transcribe_one_json.py`：被 `export-bilibili.py` 调用，输出 JSON 格式结果。

## 后续流程

导出完成后，和 Cubox 一样执行：

```bash
make all
```

Agent 会基于文字稿内容判断 quarantine 和 `ai_tags`，然后自动迁移、生成看板。

## 关联 skill

- [[wikihub-export]]：通用分类、迁移、看板生成
- [[wikihub-import-select]]：本地 Web 面板，人工选择要导出的收藏条目
- [[wikihub-export-cubox]]：Cubox 导出
