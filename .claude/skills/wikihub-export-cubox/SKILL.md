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

### 批量导出 Cubox 文章

```bash
# 1. 检测并配置文件夹（首次或文件夹有变化时）
make detect-cubox-folders

# 2. 导出
make export-cubox
```

### 通过 Cubox Dispatcher 自动分发链接

如果你把所有待导入的链接（公众号、播客、B 站、小红书）都丢进 Cubox，可以用 Dispatcher 自动按域名分发到对应 skill：

```bash
# 预览会处理哪些卡片
make dispatch-cubox DISPATCH_ARGS="--dry-run"

# 实际分发并归档
make dispatch-cubox
```

Dispatcher 会：
1. 拉取 Cubox 中除 `WikiHub_已归档` 外的卡片。
2. 按域名分发：
   - `mp.weixin.qq.com` → 微信公众号
   - `podcasts.apple.com` → Apple 播客
   - `bilibili.com` / `b23.tv` → B 站
   - `xiaohongshu.com` → 小红书
3. 导出成功后把卡片移动到 `WikiHub_已归档` 文件夹。
4. 生成 `/tmp/wikihub-pending.json`。

使用前请先在 Cubox 中创建一个名为 `WikiHub_已归档` 的文件夹。

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

## Cubox Dispatcher（域名自动分发）

`dispatch.py` 会扫描 Cubox 中未归档的卡片，根据链接域名自动调用对应 skill 的 `export-one.py` 单链接导出脚本，导出成功后再将卡片移动到归档文件夹 `WikiHub_已归档`。

### 支持的域名映射

| 域名 | 分发目标 |
|------|----------|
| `mp.weixin.qq.com` | `wikihub-export-wechat/scripts/export-one.py` |
| `podcasts.apple.com` | `wikihub-export-podcast/scripts/export-one.py` |
| `bilibili.com`、`b23.tv` | `wikihub-export-bilibili/scripts/export-one.py` |
| `xiaohongshu.com` | `wikihub-export-xiaohongshu/scripts/export-one.py` |
| 其他域名 | 暂时跳过（普通 Cubox 文章仍使用批量 `make export-cubox`） |

### 用法

```bash
# 扫描所有非归档卡片并自动分发
make dispatch-cubox

# 只预览，不实际导出/移动
make dispatch-cubox DISPATCH_ARGS="--dry-run"

# 只扫描指定 Cubox 文件夹（按 nested_name 匹配）
make dispatch-cubox DISPATCH_ARGS="--folder 待读/技术"

# 使用自定义归档文件夹名称
make dispatch-cubox DISPATCH_ARGS="--archive-folder 我的归档"
```

### 前置要求

- Cubox 中已存在名为 `WikiHub_已归档` 的文件夹（默认名称）。
- 若不存在，脚本会提示手动创建；目前不自动创建文件夹。

### 行为

1. 调用 `cubox-cli folder list` 获取文件夹列表，确认归档文件夹。
2. 调用 `cubox-cli card list --all` 获取所有卡片，排除归档文件夹中的卡片。
3. 按域名分类，读取 `wikihub-exported.json` 预览/跳过已导出卡片。
4. 调用对应 `export-one.py` 导出；成功后执行 `cubox-cli update --id <id> --folder <归档文件夹>` 移动卡片。
5. 汇总输出成功、失败、跳过数量及失败原因。

### 错误处理

- `cubox-cli` 未认证：提示运行 `cubox-cli auth login`。
- `export-one.py` 失败：记录错误并继续处理下一张卡片，不移动该卡片。
- 移动卡片失败：记录错误，不回滚已生成的本地 markdown。

## 关联 skill

- [[wikihub-export]]：通用分类、迁移、看板生成
