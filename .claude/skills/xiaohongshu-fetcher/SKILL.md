# xiaohongshu-fetcher

通用小红书笔记获取工具 skill。通过 `xhs` CLI 或 HTTP 抓取解析单条小红书笔记，生成 Markdown 文件。

## 特性

- 只负责内容获取与 Markdown 生成，**不感知任何 WikiHub 特定文件或工作流**。
- 输入：小红书笔记 URL（支持 `xiaohongshu.com/explore/<note_id>`、`xiaohongshu.com/discovery/item/<note_id>` 和 `xhslink.com` 短链）。
- 输出：Markdown 文件 + stdout JSON。
- 图片/视频保留远程链接，不下载到本地。

## 系统依赖

- [xiaohongshu-cli](https://pypi.org/project/xiaohongshu-cli/)：提供 `xhs` 命令。
  - 安装：`uv tool install xiaohongshu-cli` 或 `pip install xiaohongshu-cli`
  - 登录：`xhs login` 或 `xhs login --qrcode`
- 若未安装或未登录，本工具会回退到 HTTP 抓取，但可能被风控拦截。此时可设置 `XHS_COOKIE` 环境变量辅助抓取。

## CLI 用法

```bash
python3 scripts/fetch.py --url URL --output-dir DIR
```

参数：

- `--url`：小红书笔记链接（必填）。
- `--output-dir`：输出目录（必填）。

示例：

```bash
python3 scripts/fetch.py \
  --url "https://www.xiaohongshu.com/explore/66a1b2c3d4e5f678" \
  --output-dir ./output
```

## 输出

### Markdown 文件

输出到 `--output-dir/<note_id>.md`，格式如下：

```markdown
---
title: "..."
url: "..."
author: "..."
fetched_at: "..."
---

# 标题

[原文链接](URL)

> 👤 作者

正文...

## 图片

![](url)
```

### stdout JSON

```json
{
  "success": true,
  "file": "DIR/<note_id>.md",
  "title": "...",
  "url": "...",
  "author": "...",
  "media_files": [],
  "metadata": {
    "note_id": "...",
    "note_type": "image|video"
  }
}
```

## 失败与退出码

- 成功：stdout 输出 JSON，`exit 0`。
- 失败：stderr 输出错误信息，`exit 1`，stdout 仍输出 `{"success": false, "error": "..."}`。
