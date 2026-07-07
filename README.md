# WikiHub

一个 **agent 驱动的个人知识导入工作流**，把微信公众号、微信读书、播客、B 站、小红书、Cubox、网页等外部资料自动化地转录、去重、打标签，并最终落地到个人 wiki。

本仓库只保存**工作流代码与配置模板**，不保存个人知识内容、导出状态或敏感密钥。

## 核心设计

- **单一主控**：`wikihub-orchestrator` 是 WikiHub 唯一的主控 skill，负责整体编排。
- **通用工具 skill**：`wechat-fetcher`、`podcast-fetcher`、`bilibili-fetcher`、`xiaohongshu-fetcher`、`weread-fetcher`、`cubox-fetcher`、`transcribe-audio` 都是低耦合的通用工具，可被其他工作流复用。
- **增量导入**：所有导出结果通过 `wikihub-exported.json` 去重，避免重复抓取、下载与转录。
- **统一管道**：导出后统一执行 `make all`（应用 agent 结果 → 同步标签 → 自动分类 → 生成看板）。
- **网页看板控制**：`make select` 启动本地选择面板，决定哪些内容值得进入 wiki。
- **单一 wiki 边界**：所有内容最终只落地到 `Tech_wiki/`；agent 不得创建其他 `*_wiki/` 目录。

## 架构

```
┌─────────────────────────────────────┐
│      wikihub-orchestrator           │
│  （WikiHub 主控：路由、去重、        │
│   生成 Markdown、状态管理）          │
└──────────────┬──────────────────────┘
               │ subprocess
    ┌──────────┼──────────┬──────────┬──────────┐
    ▼          ▼          ▼          ▼          ▼          ▼
wechat-   podcast-   bilibili-  xiaohongshu-  weread-   generic-
fetcher   fetcher    fetcher    fetcher       fetcher   web-fetcher
    │          │          │          │
    ▼          ▼          ▼          ▼
         transcribe-audio（音频转录）
```

## 支持的数据来源

| 来源 | 工具 skill | 说明 |
|---|---|---|
| 微信公众号 | `wechat-fetcher` | 抓取公众号文章为 Markdown |
| 播客 | `podcast-fetcher` | 仅支持 Apple Podcasts 链接和标准 RSS feed |
| B 站 | `bilibili-fetcher` | 下载视频音频 |
| 小红书 | `xiaohongshu-fetcher` | 抓取笔记正文与图片 |
| 微信读书 | `weread-fetcher` | 导出划线与想法 |
| Cubox | `cubox-fetcher` | 获取收藏卡片列表 |
| 网页 | `generic-web-fetcher` | 通用 HTTP/HTTPS 页面抓取 |

## 快速开始

```bash
# 1. 克隆工作流
git clone https://github.com/xiehuacheng/WikiHub.git

# 2. 进入项目目录
cd WikiHub

# 3. 准备环境变量
cp .env.example .env
# 编辑 .env，填入 WEREAD_API_KEY、DASHSCOPE_API_KEY、OSS 等配置

# 4. 查看可用命令
make help
```

## 典型工作流

### 推荐：Cubox 作为统一入口

把所有待导入的链接（公众号、Apple 播客、B 站、小红书、网页）丢进 Cubox，然后一键编排：

```bash
# 1. 在 Cubox 中创建 "WikiHub_已归档" 文件夹
# 2. 预览待处理卡片
make orchestrate-dry-run

# 3. 实际执行抓取、转录、生成 Markdown、归档
make orchestrate
```

`wikihub-orchestrator` 会自动：
1. 从 Cubox 拉取未归档卡片。
2. 按域名路由到对应工具 skill（未知 HTTP/HTTPS 域名默认路由到 `generic-web-fetcher`）。
3. 下载音频/视频后调用 `transcribe-audio` 转录。
4. 生成统一格式的 WikiHub Markdown 到 `Unmapped/`。
5. 更新 `wikihub-exported.json` 和 `/tmp/wikihub-pending.json`。
6. 把 Cubox 卡片移动到 `WikiHub_已归档`。

> 注意：网页抓取默认禁用，如需在 Cubox 工作流中启用，请在 `.claude/skills/wikihub-orchestrator/wikihub-orchestrator-config.json` 中将 `web.enabled` 设为 `true`。

### 从输入队列导入

```bash
# queue.json 格式：[{"url": "...", "title": "..."}, ...]
python3 .claude/skills/wikihub-orchestrator/scripts/orchestrate.py \
  --queue /path/to/queue.json
```

### 导出后的统一处理

```bash
make all
```

等价于：

```bash
make apply-agent-results  # 应用 agent 判断（隔离/标签）
make apply-tags           # 将标签同步到 markdown frontmatter
make relocate             # 根据 ai_tags 自动移动到 Tech_wiki/
make dashboard            # 生成 wikihub-dashboard.md
```

### 收藏夹选择导入范围

```bash
# 同步小红书/B 站收藏夹到本地缓存
make sync-favorites

# 启动选择面板（默认端口 7321，冲突时自动递增）
make select
make select-xiaohongshu
make select-bilibili
```

浏览器打开提示的地址即可筛选、标记、导出内容。B 站收藏夹配置会在首次运行 `make sync-favorites` 时自动创建，之后你只需编辑 `bilibili-export-config.json` 勾选要同步的收藏夹即可。

选择完成后，点击导出会调用 `make orchestrate --queue <selected-urls>` 统一导入。

## 单独使用工具 Skill

所有 fetcher 都可以脱离 WikiHub 单独使用：

```bash
# 微信公众号
python3 .claude/skills/wechat-fetcher/scripts/fetch.py \
  --url "https://mp.weixin.qq.com/s/xxxxx" \
  --output-dir ./output

# Apple 播客
python3 .claude/skills/podcast-fetcher/scripts/fetch.py \
  --url "https://podcasts.apple.com/cn/podcast/xxx/id123456?i=789" \
  --output-dir ./output

# B 站
python3 .claude/skills/bilibili-fetcher/scripts/fetch.py \
  --url "https://www.bilibili.com/video/BVxxxxx" \
  --output-dir ./output

# 小红书
python3 .claude/skills/xiaohongshu-fetcher/scripts/fetch.py \
  --url "https://www.xiaohongshu.com/explore/xxxxx" \
  --output-dir ./output

# 音频转录
python3 .claude/skills/transcribe-audio/scripts/transcribe.py \
  --input ./output/xxx.m4a --language auto

# 通用网页
python3 .claude/skills/generic-web-fetcher/scripts/fetch.py \
  --url "https://example.com/article" \
  --output-dir ./output

# 微信读书（需要 WEREAD_API_KEY 与配置文件）
python3 .claude/skills/weread-fetcher/scripts/fetch.py \
  --config weread-export-config.json \
  --output-dir ./output

# Cubox 卡片列表
python3 .claude/skills/cubox-fetcher/scripts/fetch.py \
  --output-json /tmp/cubox-cards.json \
  --archive-folder "WikiHub_已归档"

# 同步小红书/B 站收藏夹
python3 .claude/skills/xiaohongshu-fetcher/scripts/sync-favorites.py \
  --output-json /tmp/xhs-favorites.json
python3 .claude/skills/bilibili-fetcher/scripts/sync-favorites.py \
  --config bilibili-export-config.json \
  --output-json /tmp/bili-favorites.json
```

## 环境变量

复制 `.env.example` 为 `.env` 并填写：

| 变量 | 用途 |
|---|---|
| `WEREAD_API_KEY` | 微信读书 Skill Gateway |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope（B 站/播客转录） |
| `OSS_ACCESS_KEY_ID` | 阿里云 OSS |
| `OSS_ACCESS_KEY_SECRET` | 阿里云 OSS |
| `OSS_BUCKET` | 阿里云 OSS |
| `OSS_ENDPOINT` | 阿里云 OSS |
| `XHS_COOKIE` | 小红书 HTTP 回退抓取（可选，优先使用 xhs CLI） |

## 项目结构

```
.
├── Makefile                          # 统一命令入口
├── CLAUDE.md                         # Agent 行为约束
├── .env.example                      # 环境变量模板
├── .gitignore                        # 排除个人数据
├── README.md                         # 本文件
└── .claude/skills/
    ├── wikihub-orchestrator/         # WikiHub 主控（含选择面板）
    │   ├── scripts/                  # 编排与选择面板脚本
    │   ├── assets/                   # 选择面板前端
    │   └── wikihub-orchestrator-config.json  # 主控配置
    ├── cubox-fetcher/                # Cubox 卡片获取
    ├── cubox-fetcher/                # Cubox 卡片获取
    ├── wechat-fetcher/               # 微信公众号文章
    ├── podcast-fetcher/              # Apple Podcasts / RSS
    ├── bilibili-fetcher/             # B 站视频
    ├── xiaohongshu-fetcher/          # 小红书笔记
    ├── weread-fetcher/               # 微信读书笔记
    ├── generic-web-fetcher/          # 通用网页抓取
    └── transcribe-audio/             # 音频转录
```

旧有的 `wikihub-export-*` 单一来源 skill 已迁移并删除；`wikihub-import-select` 选择面板已整合进 `wikihub-orchestrator`，统一由主控 skill 调用通用工具 skill 完成导入。

## 注意事项

- 本仓库是一个**可复用的工作流模板**，不内含任何个人 wiki 内容、导出配置、URL 列表或 `.env` 文件；这些都被 `.gitignore` 排除。
- 在公开仓库中使用前，请确认你已删除或忽略了本地个人数据（`Unmapped/`、`wikihub-exported.json`、`.claude/skills/wikihub-orchestrator/wikihub-orchestrator-config.json` 等）。
- 所有来源共享 `/tmp/wikihub-pending.json` 作为 agent 待审队列。
- 去重键格式为 `{source}_{id}`，例如 `wechat_<article_id>`、`podcast_<episode_id>`、`bilibili_<bvid>`、`xhs_<note_id>`、`web_<url_sha256>`。
- 后续 agent 不得创建 `Tech_wiki/` 以外的任何 wiki 目录。
- 工具 skill（`*-fetcher`、`transcribe-audio`）不依赖 WikiHub，可单独在其他工作流中使用。

## 技术选型参考

WikiHub 的网页抓取方案参考了 [Agent Reach](https://github.com/Panniantong/agent-reach) 的推荐，采用 [Jina Reader](https://r.jina.ai/) 作为首选抓取方式。后续在接入新的外部来源时，建议先查阅 Agent Reach 的当前选型与最佳实践，以便复用经过验证的抓取策略。

## 许可证

[MIT License](LICENSE)

你可以自由使用、修改和分发本工作流，只需保留原始版权声明。本仓库按“原样”提供，不包含任何担保。
