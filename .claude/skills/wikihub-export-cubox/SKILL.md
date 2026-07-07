---
name: wikihub-export-cubox
description: >
  将 Cubox 收藏文章导出为本地 Markdown source 文件，写入 Unmapped/ 或 cubox-export-config.json 映射的 wiki raw 目录。
  生成 /tmp/wikihub-pending.json 供后续 Agent 分类。
metadata:
  version: "1.0.0"
  author: orange
  tags: "cubox, export, knowledge-management"
  triggers: "导出 Cubox, 同步 Cubox, Cubox 到 WikiHub"
---

# Cubox 导出 Skill

将 Cubox 收藏文章批量导出到 WikiHub，后续通过 `wikihub-export` skill 的分类管道进行打标签、隔离、迁移和看板生成。

## 前置要求

- 已安装并登录 `cubox-cli`

## 配置

项目根目录 `cubox-export-config.json`：

```json
{
  "folders": [
    { "name": "深度学习", "target_wiki": "Tech_wiki/00-Raw", "enabled": true },
    { "name": "Uncategorized", "target_wiki": "", "enabled": true }
  ]
}
```

- `name`：Cubox 中的文件夹名。
- `target_wiki`：目标 wiki raw 目录。留空表示进入 `Unmapped/` 等 Agent 分类。
- `enabled`：`false` 表示跳过该文件夹。

### 自动检测文件夹

```bash
make detect-cubox-folders
```

会读取当前 Cubox 中的所有文件夹，合并到 `cubox-export-config.json`，新增的文件夹默认 `enabled: true`、`target_wiki: ""`。

## 用法

```bash
# 1. 检测并配置文件夹（首次或文件夹有变化时）
make detect-cubox-folders

# 2. 导出
make export-cubox
```

## 行为

1. 调用 `cubox-cli card list --all` 获取所有卡片。
2. 已导出的卡片（记录在 `wikihub-exported.json`）会跳过。
3. 根据 `cubox-export-config.json` 决定初始落点：
   - `enabled: false` → 跳过
   - `target_wiki` 非空 → 对应 wiki 的 `00-Raw/`
   - `target_wiki` 留空 → `Unmapped/`
4. 生成 `/tmp/wikihub-pending.json`，供 Agent 判断 quarantine 和 `ai_tags`。

## 输出文件格式

```markdown
---
cubox_id: "7446579364877044902"
title: "..."
url: "..."
folder: "Uncategorized"
tags: []
ai_tags: []
created_at: "..."
updated_at: "..."
read: false
starred: false
exported_at: "..."
---

# 文章标题

（正文）
```

## 关联 skill

- [[wikihub-export]]：通用分类、迁移、看板生成
