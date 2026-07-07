---
name: wikihub-import-select
description: >
  本地 Web 选择面板：当用户要求“导入小红书/B 站收藏夹”时，Agent 在后台启动选择面板，
  用户在浏览器中完成 selected / rejected / skipped 决策，回复“继续”后 Agent 再执行实际导入。
metadata:
  version: "1.0.0"
  author: orange
  tags: "wikihub, xiaohongshu, bilibili, selection, dashboard, favorites, import"
  triggers: >
    导入小红书收藏夹, 导入 B 站收藏夹, 导入 bilibili 收藏夹,
    打开 WikiHub 选择面板, wikihub-import-select, 打开选择面板,
    继续导入, 我选完了, 选择完成
---

# WikiHub Import Select Skill

本 skill 让 Agent 能够把“批量导入”拆成以下步骤：

0. **Agent 执行 sync**：拉取最新收藏夹数据到 `wikihub-favorites-cache.json`
1. **Agent 启动选择面板**（后台运行）
2. **用户在浏览器里逐条决策**（选中 / 跳过 / 拒绝）
3. **用户回复“继续”后，Agent 执行实际导入**

最终选中的条目会写入 `.urls` 文件，再调用现有导出 skill 生成 Markdown。

## Agent 工作流

### 0. 同步最新收藏夹数据

Agent 执行：

```bash
make sync-favorites
```

这会拉取最新收藏夹数据到 `wikihub-favorites-cache.json`，供选择面板读取。
`agent-helper.py launch` 在启动面板前也会自动执行一次同步；若同步失败则使用已有缓存并打印警告。

### 1. 用户说“导入小红书/B 站收藏夹”

Agent 执行：

```bash
# 小红书
python3 .claude/skills/wikihub-import-select/scripts/agent-helper.py launch --platform xiaohongshu

# B 站
python3 .claude/skills/wikihub-import-select/scripts/agent-helper.py launch --platform bilibili
```

这会后台启动 FastAPI 面板，输出包含 `url`、`pid`、`platforms` 的 JSON，并把会话写入 `/tmp/wikihub-select-session.json`。

然后 Agent 回复用户：

> 已启动 WikiHub 选择面板：http://127.0.0.1:7321
> 请在浏览器中选中想导入的条目，选完后回复“继续”。

### 2. 用户在浏览器中决策

浏览器打开面板后，对每条目点击：

- ✅ 选择（selected）—— 加入导出候选
- ❌ 拒绝（rejected）—— 不再显示
- ⏭ 跳过（skipped）—— 暂时不导出，下次仍会出现

决策会实时写入 `wikihub-selection-state.json`。

### 3. 用户回复“继续 / 我选完了”

Agent 执行：

```bash
python3 .claude/skills/wikihub-import-select/scripts/agent-helper.py export
```

这会读取会话信息，调用面板的 `/api/export` 接口：

- 把 `selected` 且未导出的条目写入 `xiaohongshu-selected.urls` / `bilibili-selected.urls`
- 自动调用 `export-xiaohongshu.py` / `export-bilibili.py`（带 `--yes`）
- 等待导出完成并输出日志

导出完成后，Agent 可继续执行常规分类管道：

```bash
make all
```

### 4. 关闭面板

导入完成后，Agent 可关闭后台面板：

```bash
python3 .claude/skills/wikihub-import-select/scripts/agent-helper.py stop
```

## 前置要求

- Python 3.12+
- 已安装并登录对应平台的 CLI：
  - 小红书：`uv tool install xiaohongshu-cli && xhs login`
  - B 站：`uv tool install bilibili-cli && bili login`
- 已配置 `bilibili-export-config.json`（B 站选择面板需要知道读取哪些收藏夹）。
- 首次使用前创建虚拟环境并安装依赖（之后 `agent-helper.py` 会自动使用该 venv）：
  ```bash
  cd .claude/skills/wikihub-import-select
  uv venv --python 3.12
  uv pip install -r requirements.txt
  ```

## 手动用法（不通过 Agent）

```bash
# 拉取最新收藏夹数据到 wikihub-favorites-cache.json
make sync-favorites

# 启动本地选择面板，默认在 http://127.0.0.1:7321
make select

# 默认打开小红书 / B 站标签
make select-xiaohongshu
make select-bilibili

# 指定端口
PORT=8080 make select

# 不自动打开浏览器
python3 .claude/skills/wikihub-import-select/scripts/dashboard.py --no-open
```

手动模式下，面板只提供选择/拒绝/跳过功能；同步和导出仍由 Agent 或 `make sync-favorites` / `agent-helper.py export` 完成。

## 选择工作流

1. 启动面板时读取两个来源：
   - 小红书：`xhs favorites --json` 拉取全部收藏笔记。
   - B 站：`bilibili-export-config.json` 中 `enabled: true` 的收藏夹，分别执行 `bili favorites <id> --json`。
2. 过滤已处理条目：
   - 已写入 `wikihub-exported.json` 的条目不再显示。
   - 已在 `wikihub-selection-state.json` 中有决策记录的条目不再显示。
3. 用户对每条目做决策：
   - **选中（selected）**：加入导出候选。
   - **跳过（skipped）**：仅记录状态，暂时不导出。
   - **拒绝（rejected）**：记录状态，不再导出。
4. Agent 调用 `agent-helper.py export` 后：
   - 将当前 `selected` 且尚未导出的条目写入：
     - `xiaohongshu-selected.urls`
     - `bilibili-selected.urls`
   - 自动调用 `export-xiaohongshu.py` / `export-bilibili.py` 执行导出（带 `--yes`）。
5. 导出完成后，和往常一样执行 `make all` 进行分类、迁移和看板生成。

## 文件说明

| 文件 | 作用 |
|---|---|
| `wikihub-favorites-cache.json` | 从各平台拉取的最新收藏夹数据缓存 |
| `wikihub-selection-state.json` | 保存所有决策历史（选中/跳过/拒绝）、决策时间、条目元数据 |
| `xiaohongshu-selected.urls` | 当前选中的小红书笔记 URL，每行一个 |
| `bilibili-selected.urls` | 当前选中的 B 站视频 URL，每行一个 |
| `wikihub-exported.json` | 已导出条目索引，面板会自动跳过这些条目避免重复 |
| `/tmp/wikihub-select-session.json` | 当前后台面板会话（url、pid、platforms） |

## 端口

- 默认端口：`7321`
- 通过环境变量 `PORT` 覆盖；冲突时自动递增。

## 关联 skill

- [[wikihub-export]]：通用分类、迁移、看板生成
- [[wikihub-export-xiaohongshu]]：小红书笔记导出
- [[wikihub-export-bilibili]]：B 站视频导出与转录
