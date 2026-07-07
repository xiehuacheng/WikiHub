---
name: wikihub-export-wechat
description: >
  将微信公众号文章导出为本地 Markdown source 文件，写入 Unmapped/ 或 wechat-export-config.json 映射的 wiki raw 目录。
  通过 curl + BeautifulSoup 抓取 mp.weixin.qq.com 页面正文，生成 /tmp/wikihub-pending.json 供后续 Agent 分类。
metadata:
  version: "1.0.0"
  author: orange
  tags: "wechat, export, knowledge-management"
  triggers: "导出公众号文章, 同步微信公众号, 微信公众号导出"
---

# 微信公众号文章导出 Skill

将微信公众号文章批量导出为本地 Markdown source 文件，后续通过 `wikihub-export` skill 的分类管道进行打标签、隔离、迁移和看板生成。

## 前置要求

- 已安装依赖：
  ```bash
  cd .claude/skills/wikihub-export-wechat
  uv venv --python 3.12
  uv pip install -r requirements.txt
  ```
- 已创建 `wechat-export-config.json` 配置要导出的 URL 列表。

## 配置

项目根目录 `wechat-export-config.json`：

```json
{
  "folders": [
    { "name": "微信公众号文章列表", "source": "urls", "urls_file": "wechat-articles.urls", "target_wiki": "", "enabled": true }
  ]
}
```

- `name`：列表名称，仅用于日志可读性。
- `source`：数据来源。当前仅支持 `urls`。
- `urls_file`：指向项目根目录下的 `.urls` 文件，每行一个公众号文章链接。
- `target_wiki`：目标 wiki raw 目录。留空表示进入 `Unmapped/` 等 Agent 分类。
- `enabled`：`false` 表示跳过该列表。

### 自动初始化配置

```bash
make detect-wechat-folders
```

会创建/更新 `wechat-export-config.json`，默认添加一个 `enabled: false` 的 "微信公众号文章列表"。
如果项目根目录下不存在 `wechat-articles.urls`，该命令会自动创建一个空文件，并提示你在其中每行放一个公众号文章链接。

## 用法

```bash
# 1. 初始化配置（首次）
make detect-wechat-folders

# 2. 编辑 wechat-export-config.json 将 enabled 设为 true，并配置 target_wiki

# 3. 导出
make export-wechat
```

`make export-wechat` 会先扫描所有 `enabled: true` 的 folder，列出待导出的文章清单（列表、URL、目标路径），并提示确认；确认后才会开始抓取页面并导出。

### 直接导出指定 URL 列表

```bash
# 仅导出 wechat-selected.urls 中的文章（非交互）
python3 .claude/skills/wikihub-export-wechat/scripts/export-wechat.py \
  --urls-file wechat-selected.urls --yes
```

## 行为

1. 读取 `wechat-export-config.json`。
2. 对每个 `enabled: true` 的 folder，读取 `urls_file` 中的文章链接。
3. 跳过已在 `wikihub-exported.json` 中的文章（key 为 `wechat_<article_id>`）。
4. 对未导出的文章：
   - 使用 `curl` 抓取 `mp.weixin.qq.com` 页面。
   - 使用 `BeautifulSoup` 解析 `rich_media_title`、`rich_media_meta_nickname`、`rich_media_content`。
   - 检测风控关键词（`环境异常`、`请在微信客户端`）和正文长度小于 100 字符的情况，视为失败。
5. 生成 source markdown 文件：
   ```yaml
   ---
   wechat_article_id: "MzI..._224748..._1"
   title: "..."
   url: "https://mp.weixin.qq.com/s/..."
   folder: "微信公众号文章列表"
   tags: [公众号]
   ai_tags: []
   author: "..."
   exported_at: "2026-07-04T12:00:00+00:00"
   ---
   ```
   `title`、`folder`、`author` 等字段使用 YAML 双引号字符串，并会对换行符、制表符、反斜杠和双引号进行转义，确保 frontmatter 合法。
6. 生成 `/tmp/wikihub-pending.json`，其中 `snippet` 为正文前 2000 字，供 Agent 分类使用。

## 调试脚本

- `scripts/fetch_article.py`：解析单篇公众号文章，输出 JSON。

## 后续流程

导出完成后，和 Cubox/B 站/小红书一样执行：

```bash
make all
```

Agent 会基于正文内容判断 quarantine 和 `ai_tags`，然后自动迁移、生成看板。

## 关联 skill

- [[wikihub-export]]：通用分类、迁移、看板生成
- [[wikihub-import-select]]：本地 Web 面板，人工选择要导出的收藏条目
- [[wikihub-export-cubox]]：Cubox 导出
- [[wikihub-export-bilibili]]：B 站收藏夹导出
- [[wikihub-export-xiaohongshu]]：小红书收藏夹导出
