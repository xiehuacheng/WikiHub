---
name: wikihub-orchestrator
description: >
  WikiHub 主控 skill。负责整体工作流编排：从 Cubox 或输入队列获取待导入条目，
  按域名路由到通用工具 skill（wechat-fetcher、podcast-fetcher、bilibili-fetcher、xiaohongshu-fetcher），
  统一生成 WikiHub Markdown；同时提供收藏夹选择面板，管理 WikiHub 状态文件，并可选归档 Cubox 卡片。
metadata:
  version: "1.0.0"
  author: orange
  tags: "wikihub, orchestrator, cubox, wechat, podcast, bilibili, xiaohongshu, knowledge-management"
  triggers: "整理 WikiHub, 导入 WikiHub, 运行 WikiHub 编排器, make orchestrate"
---

# wikihub-orchestrator

WikiHub 唯一特定的主控 skill。它本身不直接抓取任何外部内容，而是通过 subprocess 调用通用工具 skill 完成抓取、转录和归档；收藏夹的选择面板也作为其一部分提供。

## 职责

- 从 Cubox 拉取未归档卡片，或读取 `--queue` 指定的输入队列。
- 按 URL 域名路由到对应工具 skill。
- 维护 WikiHub 状态：`wikihub-exported.json`、`wikihub-orchestrator-config.json`、`/tmp/wikihub-pending.json`。
- 对含音频的内容自动调用 `transcribe-audio` 并追加转录文本。
- 生成统一格式的 WikiHub Markdown 到 `Unmapped/` 或配置的 `target_wiki`。
- 可选归档 Cubox 卡片到指定文件夹。
- 提供本地 Web 选择面板，用于小红书/B 站收藏夹的筛选与导出。
- 提供后续统一管道脚本：`apply-agent-results`、`apply-tags`、`relocate-by-classification`、`generate-dashboard`。

## 用法

```bash
# 从 Cubox 拉取并执行完整导入流程
python3 .claude/skills/wikihub-orchestrator/scripts/orchestrate.py

# 预览模式（不实际抓取、不转录、不归档、不写文件）
python3 .claude/skills/wikihub-orchestrator/scripts/orchestrate.py --dry-run

# 从指定队列文件导入
python3 .claude/skills/wikihub-orchestrator/scripts/orchestrate.py --queue /tmp/queue.json

# 指定自定义配置文件
python3 .claude/skills/wikihub-orchestrator/scripts/orchestrate.py --config my-config.json
```

推荐通过 Makefile 调用：

```bash
make orchestrate
make orchestrate-dry-run
make all
```

## 收藏夹选择面板

```bash
# 同步小红书/B 站收藏夹到本地缓存
make sync-favorites

# 启动选择面板（默认端口 7321，冲突时自增）
make select
make select-xiaohongshu
make select-bilibili
```

面板入口为 `assets/index.html`，由 `scripts/select_dashboard.py` 通过 FastAPI 提供。
选中项会交给 `scripts/orchestrate.py --queue <selected.json>` 统一导入。

B 站收藏夹需要先在项目根目录创建 `bilibili-export-config.json`（可参考 `bilibili-export-config.example.json`），勾选要同步的收藏夹。

## 配置文件

默认读取项目根目录下的 `wikihub-orchestrator-config.json`：

```json
{
  "archive_folder": "WikiHub_已归档",
  "target_wiki": "",
  "sources": {
    "wechat": {"enabled": true},
    "podcast": {"enabled": true},
    "bilibili": {"enabled": true},
    "xiaohongshu": {"enabled": true},
    "web": {"enabled": false},
    "weread": {"enabled": false}
  }
}
```

- `archive_folder`：Cubox 归档文件夹名称。
- `target_wiki`：留空则输出到 `Unmapped/`，否则输出到指定 wiki 目录。
- `sources.*.enabled`：是否启用对应来源的导入。

## 输入队列格式

`--queue` 文件为 JSON 数组：

```json
[
  {"url": "https://mp.weixin.qq.com/s/xxx", "title": "...", "id": "cubox-card-id-optional"},
  {"url": "https://podcasts.apple.com/...", "title": "..."}
]
```

## 域名路由

| 域名 | 工具 skill | source |
|---|---|---|
| `mp.weixin.qq.com` | `wechat-fetcher` | `wechat` |
| `podcasts.apple.com` | `podcast-fetcher` | `podcast` |
| `bilibili.com` / `b23.tv` | `bilibili-fetcher` | `bilibili` |
| `xiaohongshu.com` / `xhslink.com` | `xiaohongshu-fetcher` | `xiaohongshu` |
| 其他 HTTP/HTTPS 页面 | `generic-web-fetcher` | `web`（默认关闭） |
| 其他 | 跳过 | - |

> 微信读书通过 `weread-fetcher` 单独使用，不通过 Cubox 路由。

## 输出

- 在 `Unmapped/` 或 `target_wiki/` 下生成 Markdown 文件。
- 更新 `wikihub-exported.json`，键为来源特定 ID（如 `wechat_<article_id>`、`bilibili_<bvid>`、`xhs_<note_id>`）。
- 追加成功条目到 `/tmp/wikihub-pending.json`。
- 输出成功 / 失败 / 跳过统计报告。

## 依赖

- Python 3.10+
- `pyyaml`
- `fastapi`、`uvicorn`、`python-multipart`、`jinja2`（选择面板使用）
- 各工具 skill 的依赖（见各自 `requirements.txt`）
