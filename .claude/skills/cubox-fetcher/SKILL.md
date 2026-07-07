---
name: cubox-fetcher
description: >
  通用 Cubox 卡片列表获取工具。
  调用 cubox-cli 拉取所有卡片，排除指定归档文件夹后输出 JSON 数组。
  不感知 WikiHub，可被任意工作流复用。
metadata:
  version: "1.0.0"
  author: orange
  tags: "cubox, fetch, knowledge-management"
  triggers: "获取 Cubox 卡片, Cubox 列表"
---

# cubox-fetcher

通用工具 skill：从 Cubox 获取未归档卡片列表并输出为 JSON。

- 不做域名分类
- 不做去重
- 不调用任何内容 fetcher
- 不移动/归档卡片
- 不读取/写入 WikiHub 特定文件（如 `wikihub-exported.json`、`*-export-config.json`、`/tmp/wikihub-pending.json` 等）

## 前置条件

- 已安装并登录 [`cubox-cli`](https://github.com/orange/cubox-cli)（或你所在环境使用的 cubox-cli）。
- 确保 `cubox-cli card list --all -o json` 可以正常返回数据。

## CLI 用法

```bash
python3 .claude/skills/cubox-fetcher/scripts/fetch.py --output-json PATH [--archive-folder NAME]
```

### 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--output-json` | 是 | 输出卡片列表的 JSON 文件路径。 |
| `--archive-folder` | 否 | 要排除的归档文件夹名称，默认 `WikiHub_已归档`。 |

### 示例

```bash
# 默认排除 WikiHub_已归档
python3 .claude/skills/cubox-fetcher/scripts/fetch.py --output-json /tmp/cubox-cards.json

# 指定自定义归档文件夹
python3 .claude/skills/cubox-fetcher/scripts/fetch.py \
  --output-json /tmp/cubox-cards.json \
  --archive-folder "已读/归档"
```

## 输出 JSON 格式

输出为一个 JSON 数组，每个元素表示一张卡片：

```json
[
  {
    "id": "7474010351919432618",
    "title": "文章标题",
    "url": "https://example.com/article",
    "domain": "example.com",
    "folder": {
      "id": "...",
      "name": "Uncategorized",
      "nested_name": "Uncategorized"
    },
    "create_time": "...",
    "update_time": "..."
  }
]
```

字段说明：

- `id`：Cubox 卡片 ID（字符串）。
- `title`：卡片标题。
- `url`：卡片链接。
- `domain`：从 URL 提取的域名（已去掉 `www.` 前缀）。
- `folder`：卡片所在文件夹信息。
- `create_time` / `update_time`：Cubox 返回的创建/更新时间。

## 错误处理

- `cubox-cli` 未认证或返回非零退出码：向 stderr 输出错误信息，返回非零退出码。
- `cubox-cli` 输出无法解析为 JSON：向 stderr 输出错误信息，返回非零退出码。
- 输出目录不存在时会自动创建父目录。

## 与其他工具的关系

`cubox-fetcher` 只负责获取卡片元数据。下游工作流可读取 `--output-json` 文件，根据 `domain`、`folder` 等字段自行决定如何处理每张卡片。
