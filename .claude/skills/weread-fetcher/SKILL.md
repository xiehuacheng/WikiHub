---
name: weread-fetcher
description: >
  通用微信读书笔记获取工具。
  调用微信读书 Skill Gateway 拉取书籍列表、划线和想法，输出为本地 Markdown 文件。
  不感知 WikiHub，可被任何工作流复用。
metadata:
  version: "1.0.0"
  author: orange
  tags: "weread, wechat-reading, fetch, knowledge-management"
  triggers: "获取微信读书笔记, 导出微信读书笔记"
---

# weread-fetcher

通用工具 skill：从微信读书获取有笔记的书籍列表、划线和想法，并为每本书生成 Markdown 文件。

- 不做 WikiHub 状态管理
- 不读取 `wikihub-exported.json`、`*-export-config.json`、`/tmp/wikihub-pending.json` 等 WikiHub 特定文件
- 不移动/分类/归档输出文件
- 通过通用 CLI 接口与外部工作流交互

## 前置条件

- Python 3.10+
- 有效的微信读书 Skill Gateway API Key：
  - 通过 `--config` 的 `api_key` 字段提供，或
  - 通过环境变量 `WEREAD_API_KEY` 提供，或
  - 在当前工作目录的 `.env` 文件中设置 `WEREAD_API_KEY=wrk-xxx`

## CLI 用法

```bash
# 批量导出（默认）
python3 .claude/skills/weread-fetcher/scripts/fetch.py --config CONFIG --output-dir DIR

# 单本书导出
python3 .claude/skills/weread-fetcher/scripts/fetch.py --config CONFIG --output-dir DIR --book-id BOOK_ID
```

### 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--config` | 是 | JSON 配置文件路径。 |
| `--output-dir` | 是 | Markdown 输出目录。目录不存在时会自动创建。 |
| `--book-id` | 否 | 只导出指定书籍的笔记。 |

## 配置文件格式

```json
{
  "api_key": "wrk-xxx",
  "folders": [
    { "name": "全部笔记", "source": "notebooks", "enabled": true }
  ]
}
```

- `api_key`：微信读书 Skill Gateway API Key。留空时从环境变量 `WEREAD_API_KEY` 或当前目录 `.env` 读取。
- `folders`：批量导出时要处理的 folder 列表。
  - `name`：folder 名称，仅用于日志可读性。
  - `source`：数据来源，当前仅支持 `notebooks`（拉取全部有笔记的书籍）。
  - `enabled`：`false` 表示跳过该 folder。

## 行为

1. 读取配置文件，获取 API Key（配置 -> 环境变量 -> `.env`）。
2. 批量模式：对每个 `enabled: true` 且 `source == "notebooks"` 的 folder，拉取有笔记的书籍列表。
3. 单书模式：拉取书籍列表并定位指定 `book_id`；若未找到则报错。
4. 对每本书拉取划线（`/book/bookmarklist`）和想法（`/review/list/mine`）。
5. 在 `--output-dir` 中为每本书生成一个 Markdown 文件，文件名基于书名。
6. stdout 输出 JSON 数组，每个元素表示一本书的处理结果。

## 输出 Markdown 格式

```markdown
---
title: "..."
url: "..."
author: "..."
fetched_at: "..."
---

# 书名

[微信读书链接](URL)

## 划线

### 章节名

> 划线内容

想法：...
```

## 输出 JSON 格式

成功时 stdout 输出 JSON 数组，每个元素形如：

```json
[
  {
    "success": true,
    "file": "DIR/xxx.md",
    "title": "...",
    "url": "https://weread.qq.com/web/bookDetail/xxx",
    "author": "...",
    "media_files": [],
    "metadata": { "book_id": "...", "source": "notebooks" }
  }
]
```

失败时对应元素 `success` 为 `false` 并包含 `error` 字段：

```json
[
  {
    "success": false,
    "error": "...",
    "metadata": { "book_id": "...", "source": "notebooks" }
  }
]
```

## 错误处理

- 配置或 API Key 缺失：向 stderr 输出错误信息，stdout 输出 `[]`，返回非零退出码。
- 单本书未找到：stdout 输出包含 `success: false` 的单元素数组，返回非零退出码。
- 单本书拉取失败：该书记录 `success: false`，继续处理后续书籍。

## 与其他工具的关系

`weread-fetcher` 只负责获取微信读书笔记并生成 Markdown。下游工作流可读取 stdout 的 JSON 结果，自行决定分类、标签、迁移或去重。
