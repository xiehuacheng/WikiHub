---
name: wikihub-export-weread
description: >
  登录微信读书账号，读取配置的微信读书 notebook 列表，自动导出未导出书籍的划线与想法为 Markdown source 文件。
  通过 WeChat Reading 官方 Agent Skill Gateway（WEREAD_API_KEY 授权）拉取数据。
  写入 Unmapped/ 或配置的 wiki raw 目录，并生成 /tmp/wikihub-pending.json 供后续 Agent 分类。
metadata:
  version: "1.0.0"
  author: orange
  tags: "weread, wechat-reading, export, knowledge-management"
  triggers: "导出微信读书笔记, 同步微信读书笔记, 微信读书导出"
---

# 微信读书笔记导出 Skill

将微信读书中做过笔记的书籍批量导出为本地 Markdown source 文件，后续通过 `wikihub-export` skill 的分类管道进行打标签、隔离、迁移和看板生成。

## 前置要求

- 已通过微信读书 Skill 页面获取 `WEREAD_API_KEY`：
  ```bash
  export WEREAD_API_KEY="wrk-xxxxxxxx"
  ```
  也可以在项目根目录 `.env` 中设置；脚本启动时会自动加载该文件，如 shell 环境已存在同名变量则优先使用环境变量。
- 已创建 `weread-export-config.json` 配置要处理的 folder。

## 配置

项目根目录 `weread-export-config.json`：

```json
{
  "folders": [
    { "name": "微信读书全部笔记", "source": "notebooks", "target_wiki": "", "enabled": false }
  ]
}
```

- `name`：folder 名称，仅用于日志可读性。
- `source`：数据来源，当前仅支持 `notebooks`（拉取全部有笔记的书籍）。
- `target_wiki`：目标 wiki raw 目录。留空表示进入 `Unmapped/` 等 Agent 分类。
- `enabled`：`false` 表示跳过该 folder。

### 自动检测配置

```bash
python3 .claude/skills/wikihub-export-weread/scripts/detect-folders.py
```

会初始化 `weread-export-config.json`，检测 `WEREAD_API_KEY`，并验证能否连接微信读书 Skill Gateway。

## 用法

```bash
# 1. 检测并配置 folder（首次或配置有变化时）
python3 .claude/skills/wikihub-export-weread/scripts/detect-folders.py

# 2. 导出（交互确认）
python3 .claude/skills/wikihub-export-weread/scripts/export-weread.py

# 3. 非交互导出
python3 .claude/skills/wikihub-export-weread/scripts/export-weread.py --yes
```

`export-weread.py` 会先扫描所有 `enabled: true` 的 folder，列出待导出的书籍清单并提示确认；确认后才会开始导出。

## 行为

1. 读取 `weread-export-config.json`。
2. 对每个 `enabled: true` 的 folder：
   - `source == "notebooks"`：调用 `/user/notebooks` 拉取有笔记的书籍列表。
3. 跳过已在 `wikihub-exported.json` 中的书籍（key 为 `weread_<bookId>`）。
4. 对未导出的书籍：
   - 调用 `/book/bookmarklist` 分页获取划线（synckey + hasMore）。
   - 调用 `/review/list/mine` 获取个人想法/书评。
5. 生成 source markdown 文件：
   ```yaml
   ---
   weread_id: "3300045871"
   title: "..."
   url: "https://weread.qq.com/web/bookDetail/3300045871"
   folder: "微信读书全部笔记"
   tags: [微信读书, 计算机]
   ai_tags: []
   author: "..."
   book_type: "book"
   exported_at: "2026-07-04T12:00:00+00:00"
   source: "weread"
   ---
   ```
6. Markdown 正文按章节组织划线，并单独列出个人想法。
7. 生成 `/tmp/wikihub-pending.json`，其中 `snippet` 为正文前 2000 字，供 Agent 分类使用。

## 调试脚本

- `scripts/weread_api.py`：封装 WeRead Agent Gateway 调用与分页逻辑。
- `scripts/detect-folders.py`：初始化/更新 `weread-export-config.json`。

## 后续流程

导出完成后，和 Cubox / B 站 / 小红书一样执行：

```bash
make all
```

Agent 会基于笔记内容判断 quarantine 和 `ai_tags`，然后自动迁移、生成看板。

## 关联 skill

- [[wikihub-export]]：通用分类、迁移、看板生成
- [[wikihub-import-select]]：本地 Web 面板，人工选择要导出的收藏条目
- [[wikihub-export-cubox]]：Cubox 导出
- [[wikihub-export-bilibili]]：B 站收藏夹导出
- [[wikihub-export-xiaohongshu]]：小红书收藏夹导出
