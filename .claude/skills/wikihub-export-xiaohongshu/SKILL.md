---
name: wikihub-export-xiaohongshu
description: >
  登录小红书账号，读取配置的小红书收藏夹或 URL 列表，自动导出未导出的笔记为 Markdown source 文件。
  用 xiaohongshu-cli 获取收藏列表并优先读取笔记详情；xhs read 失败时回退到 HTTP 抓取。
  图片/视频保留远程链接，不下载到本地。
  写入 Unmapped/ 或配置的 wiki raw 目录，并生成 /tmp/wikihub-pending.json 供后续 Agent 分类。
metadata:
  version: "1.0.0"
  author: orange
  tags: "xiaohongshu, export, knowledge-management"
  triggers: "导出小红书收藏夹, 同步小红书收藏夹, 小红书收藏夹导出"
---

# 小红书收藏夹导出 Skill

将小红书收藏夹笔记批量导出为本地 Markdown source 文件，后续通过 `wikihub-export` skill 的分类管道进行打标签、隔离、迁移和看板生成。

## 前置要求

- 已安装并登录 `xiaohongshu-cli`：
  ```bash
  uv tool install xiaohongshu-cli
  xhs login
  ```
  `xhs favorites` 需要登录态才能获取收藏列表。
- 已创建 `xiaohongshu-export-config.json` 配置要处理的收藏夹或 URL 列表。
- 建议配置小红书 cookie 以便 HTTP 回退抓取更稳定：
  ```bash
  cp .env.example .env
  # 编辑 .env，填入 XHS_COOKIE
  ```
  Cookie 来源优先级：环境变量 > `.env` 文件 > `~/.xiaohongshu-cli/cookies.json`。

## 配置

项目根目录 `xiaohongshu-export-config.json`：

```json
{
  "folders": [
    { "name": "小红书全部收藏", "source": "favorites", "urls_file": "xiaohongshu-favorites.urls", "target_wiki": "", "enabled": false },
    { "name": "成长笔记", "source": "urls", "urls_file": "xiaohongshu-growth.urls", "target_wiki": "", "enabled": true },
    { "name": "技术笔记", "source": "urls", "urls_file": "xiaohongshu-tech.urls", "target_wiki": "Tech_wiki/00-Raw", "enabled": true }
  ]
}
```

- `name`：收藏夹名称，仅用于日志可读性。
- `source`：数据来源。
  - `favorites`：调用 `xhs favorites --json` 获取全部收藏 URL。
  - `urls`：读取 `urls_file` 中每行一条笔记链接。
- `urls_file`：当 `source` 为 `urls` 时必填，指向项目根目录下的 `.urls` 文件。
- `target_wiki`：目标 wiki raw 目录。留空表示进入 `Unmapped/` 等 Agent 分类。
- `enabled`：`false` 表示跳过该收藏夹。

### 自动检测收藏夹

```bash
make detect-xiaohongshu-folders
```

会初始化 `xiaohongshu-export-config.json`，检测 `xhs` CLI 与登录态，并生成 `xiaohongshu-favorites.urls`（全部收藏 URL 列表）。

## 用法

```bash
# 1. 检测并配置收藏夹（首次或配置有变化时）
make detect-xiaohongshu-folders

# 2. 通过选择面板人工筛选（推荐）
make select-xiaohongshu

# 3. 导出
make export-xiaohongshu
```

`make export-xiaohongshu` 会先扫描所有 `enabled: true` 的收藏夹，列出待导出的笔记清单，并提示确认；确认后才会开始导出。

### 直接导出指定 URL 列表

```bash
# 仅导出 xiaohongshu-selected.urls 中的笔记（非交互）
python3 .claude/skills/wikihub-export-xiaohongshu/scripts/export-xiaohongshu.py \
  --urls-file xiaohongshu-selected.urls --yes
```

## 行为

1. 读取 `xiaohongshu-export-config.json`。
2. 对每个 `enabled: true` 的收藏夹：
   - `source == "favorites"`：调用 `xhs favorites --json` 获取全部收藏 URL。
   - `source == "urls"`：读取 `urls_file` 中的笔记链接。
3. 跳过已在 `wikihub-exported.json` 中的笔记（key 为 `xhs_<note_id>`）。
4. 对未导出的笔记：
   - **首选**：调用 `xhs read <note_id>` 获取详情。
   - **回退**：如果 `xhs read` 失败，用 HTTP 抓取页面，优先解析 `window.__INITIAL_STATE__`，失败则回退 `og:` 元标签。
5. 生成 source markdown 文件：
   ```yaml
   ---
   xiaohongshu_id: "64a1b2c3d4e5f6789abcdef0"
   title: "..."
   url: "https://www.xiaohongshu.com/explore/64a1b2c3d4e5f6789abcdef0"
   folder: "成长笔记"
   tags: [小红书, 标签1, 标签2]
   ai_tags: []
   note_type: "video"
   author: "..."
   likes: "1234"
   collects: "567"
   comments: "89"
   exported_at: "2026-07-04T12:00:00+00:00"
   ---
   ```
6. Markdown 正文中图片以 `![](url)` 嵌入，视频保留直链，均不下载到本地。
7. 生成 `/tmp/wikihub-pending.json`，其中 `snippet` 为正文前 2000 字，供 Agent 分类使用。

## 调试脚本

- `scripts/fetch_one.py`：解析单条笔记，输出 JSON。
- `scripts/xhs_cli.py`：封装 `xhs` CLI 调用与 cookie 读取。

## 后续流程

导出完成后，和 Cubox/B 站一样执行：

```bash
make all
```

Agent 会基于笔记内容判断 quarantine 和 `ai_tags`，然后自动迁移、生成看板。

## 关联 skill

- [[wikihub-export]]：通用分类、迁移、看板生成
- [[wikihub-import-select]]：本地 Web 面板，人工选择要导出的收藏条目
- [[wikihub-export-cubox]]：Cubox 导出
- [[wikihub-export-bilibili]]：B 站收藏夹导出
