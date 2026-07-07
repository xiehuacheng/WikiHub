# generic-web-fetcher

通用网页正文抓取工具 skill。

对任意 HTML 页面做极简正文提取，生成 Markdown 文件。适合处理 Cubox 中除公众号、播客、B 站、小红书之外的普通网页链接。

## 特性

- 只负责内容获取与 Markdown 生成，**不感知任何 WikiHub 特定文件或工作流**。
- 输入：任意 HTTP/HTTPS 网页链接。
- 输出：Markdown 文件 + stdout JSON。
- 使用 `curl` 拉取页面，`beautifulsoup4` 提取标题与正文。

## 依赖

- Python 3.10+
- `beautifulsoup4`（见 `requirements.txt`）
- 系统 `curl`

## CLI 用法

```bash
python3 scripts/fetch.py \
  --url "https://example.com/article" \
  --output-dir ./output
```

## 输出

### Markdown 文件

输出到 `--output-dir/<safe-title>.md`，格式如下：

```markdown
---
title: "..."
url: "..."
author: "..."
fetched_at: "..."
---

# 标题

[原文链接](URL)

> 来源：...

正文...
```

### stdout JSON

```json
{
  "success": true,
  "file": "DIR/article-title.md",
  "title": "...",
  "url": "...",
  "author": "...",
  "media_files": [],
  "metadata": {
    "page_id": "sha256前12位",
    "domain": "example.com"
  }
}
```

## 失败与退出码

- 成功：`stdout` 输出 JSON，`exit 0`。
- 失败：`stderr` 输出错误信息，`exit 1`，`stdout` 仍输出 `{"success": false, "error": "..."}`。
