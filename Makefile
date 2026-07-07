# WikiHub 导入/导出工作流
# 所有命令均应在 WikiHub/ 根目录下执行
# 注意：本 Makefile 主要供 Claude Code agent 内部调用；用户通过自然语言触发 skill。

SELECT_PORT ?= $(PORT)
SELECT_PORT ?= 7321
SELECT_VENV := .claude/skills/wikihub-import-select/.venv/bin/python
SELECT_PYTHON := $(shell [ -f $(SELECT_VENV) ] && echo $(SELECT_VENV) || echo python3)

.PHONY: help detect-cubox-folders detect-bilibili-folders detect-xiaohongshu-folders detect-weread-folders detect-wechat-folders detect-podcast-folders export-cubox export-bilibili export-xiaohongshu export-weread export-wechat export-podcast dispatch-cubox sync-favorites select select-xiaohongshu select-bilibili apply-agent-results apply-tags dashboard relocate all

help:
	@echo "WikiHub 导入/导出工作流"
	@echo ""
	@echo "  make detect-cubox-folders       - 检测 Cubox 文件夹并更新 cubox-export-config.json"
	@echo "  make detect-bilibili-folders    - 检测 B 站收藏夹并更新 bilibili-export-config.json"
	@echo "  make detect-xiaohongshu-folders - 检测小红书导出环境并初始化 xiaohongshu-export-config.json"
	@echo "  make detect-weread-folders      - 检测微信读书账号并初始化 weread-export-config.json"
	@echo "  make detect-wechat-folders      - 初始化微信公众号导出配置"
	@echo "  make detect-podcast-folders     - 初始化播客导出配置"
	@echo "  make export-cubox               - 导出 Cubox 收藏文章"
	@echo "  make export-bilibili            - 导出 B 站收藏夹视频（含转录）"
	@echo "  make export-xiaohongshu         - 导出小红书收藏夹笔记（含图片下载/视频转录）"
	@echo "  make export-weread              - 导出微信读书划线与想法"
	@echo "  make export-wechat              - 导出微信公众号文章"
	@echo "  make export-podcast             - 下载并转录播客单集"
	@echo "  make dispatch-cubox             - 从 Cubox 自动分发卡片到对应 skill 导出"
	@echo "  make sync-favorites             - 拉取最新收藏夹数据到 wikihub-favorites-cache.json"
	@echo "  make select                     - 启动 WikiHub 选择面板（默认端口 7321，冲突时自增）"
	@echo "  make select-xiaohongshu         - 启动 WikiHub 选择面板（默认打开小红书标签）"
	@echo "  make select-bilibili            - 启动 WikiHub 选择面板（默认打开 B 站标签）"
	@echo "  make apply-agent-results        - 应用 agent 判断结果（隔离/标签）"
	@echo "  make apply-tags                 - 将 wikihub-tags.json 同步到 markdown frontmatter"
	@echo "  make dashboard                  - 生成中文注解看板 wikihub-dashboard.md"
	@echo "  make relocate                   - 根据 ai_tags 自动移动文章到目标 wiki"
	@echo "  make all                        - 执行导出后的自动化步骤（agent 需先写入 /tmp/wikihub-agent-results.json）"

detect-cubox-folders:
	python3 .claude/skills/wikihub-export-cubox/scripts/detect-folders.py

detect-bilibili-folders:
	python3 .claude/skills/wikihub-export-bilibili/scripts/detect-folders.py

detect-xiaohongshu-folders:
	python3 .claude/skills/wikihub-export-xiaohongshu/scripts/detect-folders.py

detect-weread-folders:
	python3 .claude/skills/wikihub-export-weread/scripts/detect-folders.py

detect-wechat-folders:
	python3 .claude/skills/wikihub-export-wechat/scripts/detect-folders.py

detect-podcast-folders:
	python3 .claude/skills/wikihub-export-podcast/scripts/detect-folders.py

export-cubox:
	python3 .claude/skills/wikihub-export-cubox/scripts/export-cubox.py

export-bilibili:
	python3 .claude/skills/wikihub-export-bilibili/scripts/export-bilibili.py $(EXPORT_BILIBILI_ARGS)

export-xiaohongshu:
	python3 .claude/skills/wikihub-export-xiaohongshu/scripts/export-xiaohongshu.py $(EXPORT_XIAOHONGSHU_ARGS)

export-weread:
	python3 .claude/skills/wikihub-export-weread/scripts/export-weread.py $(EXPORT_WEREAD_ARGS)

export-wechat:
	python3 .claude/skills/wikihub-export-wechat/scripts/export-wechat.py $(EXPORT_WECHAT_ARGS)

export-podcast:
	python3 .claude/skills/wikihub-export-podcast/scripts/export-podcast.py $(EXPORT_PODCAST_ARGS)

dispatch-cubox:
	python3 .claude/skills/wikihub-export-cubox/scripts/dispatch.py $(DISPATCH_ARGS)

sync-favorites:
	$(SELECT_PYTHON) .claude/skills/wikihub-import-select/scripts/sync.py

select:
	$(SELECT_PYTHON) .claude/skills/wikihub-import-select/scripts/dashboard.py --port $(SELECT_PORT)

select-xiaohongshu:
	$(SELECT_PYTHON) .claude/skills/wikihub-import-select/scripts/dashboard.py --port $(SELECT_PORT) --platform xiaohongshu

select-bilibili:
	$(SELECT_PYTHON) .claude/skills/wikihub-import-select/scripts/dashboard.py --port $(SELECT_PORT) --platform bilibili

apply-agent-results:
	python3 .claude/skills/wikihub-export/scripts/apply-agent-results.py

apply-tags:
	python3 .claude/skills/wikihub-export/scripts/apply-tags.py

dashboard:
	python3 .claude/skills/wikihub-export/scripts/generate-dashboard.py

relocate:
	python3 .claude/skills/wikihub-export/scripts/relocate-by-classification.py

# Agent 工作流：导出后由 agent 读取 /tmp/wikihub-pending.json 并生成 /tmp/wikihub-agent-results.json，
# 然后调用以下步骤完成隔离、标签同步、移动和看板生成。
all: apply-agent-results apply-tags relocate dashboard
