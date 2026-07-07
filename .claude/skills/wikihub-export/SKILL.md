---
name: wikihub-export
description: >
  WikiHub 导入/导出总 skill。负责调用来源-specific skills（Cubox、B 站收藏夹、小红书收藏夹等）导出内容，
  然后执行统一的分类、标签同步、迁移和看板生成管道。
metadata:
  version: "1.0.0"
  author: orange
  tags: "cubox, bilibili, xiaohongshu, export, classification, knowledge-management"
  triggers: "整理 WikiHub, 更新 WikiHub 导出, 重新分类 WikiHub 文章, 生成 WikiHub 看板"
---

# WikiHub 导入/导出总 Skill

本 skill 不直接处理任何外部来源，而是编排来源导出与后续分类管道。

## 子 skill

| Skill | 职责 |
|---|---|
| [[wikihub-export-cubox]] | 导出 Cubox 收藏文章 |
| [[wikihub-export-bilibili]] | 导出并转录 B 站收藏夹视频 |
| [[wikihub-export-xiaohongshu]] | 导出小红书收藏夹笔记（图文下载/视频转录） |
| [[wikihub-export-weread]] | 导出微信读书划线与想法 |
| [[wikihub-export-wechat]] | 导出微信公众号文章 |
| [[wikihub-export-podcast]] | 下载并转录播客单集 |
| [[wikihub-import-select]] | 本地 Web 面板：人工审阅并选择要导出的收藏条目 |

## 通用分类管道

来源导出后，统一执行以下步骤：

```text
导出（Cubox / B 站 / 小红书 / 其他来源）
  ↓
Agent 读取 /tmp/wikihub-pending.json
  ↓
判断 quarantine + ai_tags → 写入 /tmp/wikihub-agent-results.json
  ↓
make all
  ↓
apply-agent-results → apply-tags → relocate → dashboard
```

## 命令

```bash
# 检测并更新来源文件夹配置
make detect-cubox-folders
make detect-bilibili-folders
make detect-xiaohongshu-folders
make detect-weread-folders
make detect-wechat-folders
make detect-podcast-folders

# 人工选择要导出的条目（推荐先执行）
make sync-favorites
make select
make select-xiaohongshu
make select-bilibili

# 导出来源内容
make export-cubox
make export-bilibili
make export-xiaohongshu
make export-weread
make export-wechat
make export-podcast

# 应用 Agent 判断结果（隔离/标签）
make apply-agent-results

# 同步标签到 Markdown frontmatter
make apply-tags

# 根据 ai_tags 自动移动文章到目标 wiki
make relocate

# 生成看板
make dashboard

# 执行导出后的自动化步骤（需 Agent 已写入 /tmp/wikihub-agent-results.json）
make all
```

## Agent 判断标准

### 标题/正文是否匹配

- **匹配（match）**：正文明显是关于标题所描述的主题。
- **不匹配（mismatch）**：正文与标题描述的主题明显不符。
- **不确定（unclear）**：正文过短、为空、或无法明确判断。

对于 **mismatch** 或 **unclear** 的文章，标记为 `quarantine: true`，并填写 `quarantine_reason`。

### 主题标签

对于 **匹配** 的文章，从以下标签体系中选择 1-4 个最相关的标签：

- `ai`, `ai-agent`, `llm`, `rag`, `claude-code`, `ai-coding`, `machine-learning`, `programming`
- `productivity`, `focus`, `habits`, `study`, `procrastination`, `time-management`, `todo`
- `mental-health`, `psychology`, `adhd`, `sleep`, `health`
- `personal-growth`, `motivation`, `reflection`, `self-awareness`, `life`, `philosophy`
- `relationships`, `communication`, `emotions`
- `tools`, `notion`, `jetbrains`, `wordpress`, `mac-apps`, `apple-id`, `shopping`, `email`
- `reading`, `music`, `singing`
- `education`, `learning`, `exam-prep`, `hands-on`
- `unknown`（仅当确实无法分类时使用）

## 数据文件

| 文件 | 作用 |
|---|---|
| `cubox-export-config.json` | Cubox 文件夹 → 本地 wiki raw 路径映射 + 是否启用 |
| `bilibili-export-config.json` | B 站收藏夹 → 本地 wiki raw 路径映射 + 是否启用 |
| `xiaohongshu-export-config.json` | 小红书收藏夹/URL 列表 → 本地 wiki raw 路径映射 + 是否启用 |
| `weread-export-config.json` | 微信读书 notebook 导出配置 |
| `wechat-export-config.json` | 微信公众号文章 URL 列表导出配置 |
| `podcast-export-config.json` | 播客 RSS/URL 列表导出配置 |
| `wikihub-selection-state.json` | 选择面板记录（selected / rejected / skipped） |
| `wikihub-exported.json` | 导出记录。key 为 card_id、bvid、xhs_\<note_id\>、weread_\<bookId\>、wechat_\<article_id\> 或 podcast_\<episode_id\> |
| `wikihub-tags.json` | card_id/bvid/xhs_\<note_id\> → AI 主题标签映射 |
| `wikihub-dashboard.md` | 当前导出状态、标签分布、Quarantine 警告 |

## 异常隔离机制

- **异常文件夹**：`Quarantine/`，位于项目根目录。
- **触发条件**：标题与正文明显不符，或正文过短无法判断。
- **人工确认**：被隔离的文章保留在 `Quarantine/`，用户可以手动查看、删除或重新收藏。

## 手动覆盖

如果用户对 agent 的自动分类结果不满意，可以手动编辑 `wikihub-tags.json`，然后运行：

```bash
make apply-tags
make relocate
make dashboard
```
