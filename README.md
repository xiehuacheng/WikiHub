# WikiHub

一个 **agent 驱动的个人知识导入工作流**，把微信公众号、微信读书、播客、B 站、小红书、Cubox 等外部资料自动化地转录、去重、打标签，并最终落地到个人 wiki。

本仓库只保存**工作流代码与配置模板**，不保存个人知识内容、导出状态或敏感密钥。

## 核心设计

- **自然语言触发**：用户对 agent 说“导出微信读书”“导出这期播客”，agent 调用对应 skill 执行导出。
- **增量导入**：所有导出结果通过 `wikihub-exported.json` 去重，避免重复抓取、下载与转录。
- **统一管道**：导出后统一执行 `make all`（应用 agent 结果 → 同步标签 → 自动分类 → 生成看板）。
- **网页看板控制**：`make select` 启动本地选择面板，决定哪些内容值得进入 wiki。
- **单一 wiki 边界**：所有内容最终只落地到 `Tech_wiki/`；agent 不得创建其他 `*_wiki/` 目录。

## 支持的数据来源

| 来源 | 命令 | 说明 |
|---|---|---|
| 微信读书 | `make export-weread` | 基于 WeChat Reading Skill Gateway 导出划线与想法 |
| 微信公众号 | `make export-wechat` / `export-one.py --url` | 抓取公众号文章为 Markdown |
| 播客 | `make export-podcast` / `export-one.py --url` | 仅支持 Apple Podcasts 链接和标准 RSS feed |
| B 站 | `make export-bilibili` / `export-one.py --url` | 导出收藏夹视频或单个视频并转录 |
| 小红书 | `make export-xiaohongshu` / `export-one.py --url` | 导出收藏笔记或单条笔记 |
| Cubox | `make export-cubox` / `make dispatch-cubox` | 批量导出文章，或作为统一入口分发链接 |

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

把所有待导入的链接（公众号、Apple 播客、B 站、小红书）丢进 Cubox，然后一键分发：

```bash
# 1. 在 Cubox 中创建 "WikiHub_已归档" 文件夹
# 2. 预览待处理卡片
make dispatch-cubox DISPATCH_ARGS="--dry-run"

# 3. 实际分发、导出、归档
make dispatch-cubox
```

Dispatcher 会自动按域名分发到对应 skill，导出成功后把卡片移动到 `WikiHub_已归档`。

### 传统：逐个来源导出

#### 初始化

```bash
make detect-weread-folders   # 生成 weread-export-config.json
make detect-wechat-folders   # 生成 wechat-export-config.json 和 wechat-articles.urls
make detect-podcast-folders  # 生成 podcast-export-config.json 和 podcast-feeds.urls
```

编辑生成的 `*-export-config.json`，将 `enabled` 设为 `true`；对于公众号和播客，在对应的 `.urls` 文件中每行放入一个链接。

#### 批量导出

```bash
make export-weread --yes
make export-wechat --yes
make export-podcast --yes
```

#### 单链接导出

```bash
# 微信公众号
python3 .claude/skills/wikihub-export-wechat/scripts/export-one.py \
  --url "https://mp.weixin.qq.com/s/xxxxx"

# Apple 播客
python3 .claude/skills/wikihub-export-podcast/scripts/export-one.py \
  --url "https://podcasts.apple.com/cn/podcast/xxx/id123456?i=789"

# B 站
python3 .claude/skills/wikihub-export-bilibili/scripts/export-one.py \
  --url "https://www.bilibili.com/video/BVxxxxx"

# 小红书
python3 .claude/skills/wikihub-export-xiaohongshu/scripts/export-one.py \
  --url "https://www.xiaohongshu.com/explore/xxxxx"
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

### 网页看板选择导入范围

```bash
make select
```

默认端口 `7321`，冲突时自动递增。浏览器打开提示的地址即可筛选、标记、导出内容。

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

## 项目结构

```
.
├── Makefile                          # 统一命令入口
├── CLAUDE.md                         # Agent 行为约束
├── .env.example                      # 环境变量模板
├── .gitignore                        # 排除个人数据
├── README.md                         # 本文件
└── .claude/skills/
    ├── wikihub-export/               # 统一管道脚本
    ├── wikihub-export-bilibili/      # B 站导出
    ├── wikihub-export-cubox/         # Cubox 导出
    ├── wikihub-export-podcast/       # 播客导出
    ├── wikihub-export-wechat/        # 微信公众号导出
    ├── wikihub-export-weread/        # 微信读书导出
    ├── wikihub-export-xiaohongshu/   # 小红书导出
    └── wikihub-import-select/        # 网页看板与选择面板
```

## 注意事项

- 本仓库是一个**可复用的工作流模板**，不内含任何个人 wiki 内容、导出配置、URL 列表或 `.env` 文件；这些都被 `.gitignore` 排除。
- 在公开仓库中使用前，请确认你已删除或忽略了本地个人数据（`Unmapped/`、`*-export-config.json`、`*.urls`、`wikihub-exported.json` 等）。
- 所有来源共享 `/tmp/wikihub-pending.json` 作为 agent 待审队列。
- 去重键格式为 `{source}_{id}`，例如 `weread_<bookId>`、`wechat_<article_id>`、`podcast_<episode_id>`。
- 后续 agent 不得创建 `Tech_wiki/` 以外的任何 wiki 目录。

## 许可证

[MIT License](LICENSE)

你可以自由使用、修改和分发本工作流，只需保留原始版权声明。本仓库按“原样”提供，不包含任何担保。
