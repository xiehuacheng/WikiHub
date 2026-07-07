# CLAUDE.md — WikiHub Agent 协作指南

本文件约束所有操作 WikiHub 项目的 agent 行为。WikiHub 是一个 **agent 驱动的外部资料导入中枢**，统一接收微信公众号、微信读书、播客、B 站、小红书、Cubox、网页等来源的内容，并只落地到 `Tech_wiki/` 这一个正式 wiki 中。

## 核心原则

1. **只做增量导入**：所有导出脚本必须通过 `wikihub-exported.json` 去重，避免重复抓取、重复下载、重复转录。
2. **只有一个合法 wiki**：`Tech_wiki/` 是 WikiHub 中唯一合法的 wiki 目录。
3. **禁止自动创建新 wiki**：agent 不得创建任何新的 `*_wiki/` 顶层目录，除非用户明确书面授权。
4. **默认落地到 `Unmapped/`**：新导出的原始资料默认写入 `Unmapped/`，由后续分类流程决定是否移动到 `Tech_wiki/` 内部。

## 工作流

用户通过自然语言触发导出，agent 调用对应 skill，最终由 Makefile 执行：

```
用户自然语言指令
    ↓
调用 .claude/skills/wikihub-orchestrator/ 编排导入流程
    ↓
make sync-favorites        # 同步小红书/B 站收藏夹（可选）
make select                # 通过网页面板筛选要导入的收藏夹内容（可选）
    ↓
make orchestrate           # 从 Cubox/队列获取条目，路由到工具 skill 导入
    ↓
make all                   # apply-agent-results → apply-tags → relocate → dashboard
```

### 增量导入机制

- 去重键格式：`{source}_{id}`，例如 `wechat_<article_id>`、`podcast_<episode_id>`、`bilibili_<bvid>`、`xhs_<note_id>`、`web_<url_sha256>`。
- 已导出记录保存在 `wikihub-exported.json`。
- 导出脚本在拉取/转录前必须先检查该 key，已存在则跳过。
- 音频/视频转录结果也应通过同一 key 去重，避免重复调用 ASR。

### 分类与移动

- `Unmapped/` 是新内容的默认落脚点。
- `relocate-by-classification.py` 可根据 `ai_tags` 将文件移动到 `Tech_wiki/00-Raw/` 或 `Tech_wiki/02-Areas/` 下的合适子目录。
- **移动目标必须位于 `Tech_wiki/` 内部**，不得移动到任何新的 `*_wiki/` 目录。
- 如果分类结果建议创建新 wiki 目录（如 `MentalHealth_wiki/`），应拒绝执行，并将内容保留在 `Unmapped/` 或 `Tech_wiki/00-Raw/uncategorized/`，同时提示用户。

## 禁止行为

以下行为未经用户明确授权，agent 不得执行：

- 创建任何新的 `*_wiki/` 顶层目录。
- 删除 `Tech_wiki/` 内部的现有文件或目录。
- 修改 `Tech_wiki/CLAUDE.md`、`Tech_wiki/WORKFLOWS.md`、`Tech_wiki/index.md` 等 schema/核心文件。
- 在 `wikihub-exported.json` 中伪造或删除去重记录。
- 绕过 `.claude/skills/wikihub-orchestrator/wikihub-orchestrator-config.json` 的 `sources.*.enabled: false` 状态强制导出。
- 把用户未授权的 `.env` 值写入任何文件（包括日志、配置、测试脚本）。

## 环境变量

敏感配置必须来自环境变量或根目录 `.env` 文件（由调用方负责加载），不要在代码中硬编码：

- `WEREAD_API_KEY`：微信读书 Skill Gateway
- `DASHSCOPE_API_KEY`：阿里云 DashScope（B 站/播客转录）
- `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` / `OSS_BUCKET` / `OSS_ENDPOINT`：OSS 上传


## 目录结构

```
WikiHub/
├── CLAUDE.md                     # 本文件
├── .env.example                  # 环境变量模板
├── Makefile                      # 统一导出/处理入口
├── Unmapped/                     # 新导出内容默认落地目录
├── Tech_wiki/                    # 唯一合法 wiki
│   ├── CLAUDE.md                 # Tech_wiki 内部 schema 与协作指南
│   ├── WORKFLOWS.md
│   ├── 00-Raw/                   # 原始资料
│   ├── 01-Wiki/                  # 概念卡片
│   ├── 02-Areas/                 # 领域聚合
│   └── assets/                   # 附件
├── .claude/skills/wikihub-orchestrator/    # WikiHub 主控编排 skill（含选择面板）
│   ├── scripts/                            # 编排与选择面板脚本
│   └── assets/                             # 选择面板前端
├── .claude/skills/*-fetcher/               # 通用内容抓取工具 skill
└── .claude/skills/transcribe-audio/        # 音频转录工具 skill
```

## 变更记录

- 2026-07-07：新增 `wikihub-orchestrator` 主控 skill，统一从 Cubox/队列路由到通用工具 skill 导入；统一管道脚本迁移至 orchestrator；将 `wikihub-import-select` 选择面板整合进 orchestrator；为 `xiaohongshu-fetcher`/`bilibili-fetcher` 增加 `sync-favorites.py`；删除旧 `wikihub-export-*` 单一来源 skill；新增 `generic-web-fetcher` 通用网页抓取 skill 并接入 orchestrator。
- 2026-07-06：新增本指南，明确 WikiHub 为单一 Tech_wiki 入口，禁止自动创建其他 wiki 目录。
