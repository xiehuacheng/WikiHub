# wechat-fetcher

通用微信公众号文章抓取工具 skill。

这是一个通用工具 skill，可被任何工作流复用。它只负责抓取微信公众号文章内容并输出 Markdown，不感知 WikiHub 项目结构，也不管理任何 WikiHub 状态文件。

## 前置条件

- Python 3.10+
- `curl` 命令可用
- 安装依赖：`pip install -r requirements.txt`（只需要 beautifulsoup4）

## CLI 用法

```bash
python3 scripts/fetch.py --url URL --output-dir DIR
```

参数：

- `--url`：微信公众号文章链接（必填）。
- `--output-dir`：输出 Markdown 文件的目录（必填）。目录不存在时会自动创建。

## 行为

1. 使用 `curl` 携带浏览器 User-Agent 抓取微信公众号文章 HTML。
2. 解析标题、作者、正文。
3. 在 `--output-dir` 中生成 Markdown 文件，文件名基于文章标题。
4. stdout 输出 JSON 结果。

## 输出格式

成功时 stdout 输出 JSON：

```json
{
  "success": true,
  "file": "DIR/xxx.md",
  "title": "...",
  "url": "...",
  "author": "...",
  "media_files": [],
  "metadata": {
    "article_id": "..."
  }
}
```

失败时 stdout 输出 JSON 并返回非零退出码：

```json
{
  "success": false,
  "error": "..."
}
```

## 输出 Markdown 格式

```markdown
---
title: "..."
url: "..."
author: "..."
fetched_at: "2026-07-07T..."
---

# 标题

[原文链接](URL)

> 作者：...

正文...
```
