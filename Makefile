# WikiHub 导入/导出工作流
# 所有命令均应在 WikiHub/ 根目录下执行
# 注意：本 Makefile 主要供 Claude Code agent 内部调用；用户通过自然语言触发 skill。

SELECT_PORT ?= $(PORT)
SELECT_PORT ?= 7321
ORCHESTRATOR_VENV := .claude/skills/wikihub-orchestrator/.venv/bin/python
ORCHESTRATOR_PYTHON := $(shell [ -f $(ORCHESTRATOR_VENV) ] && echo $(ORCHESTRATOR_VENV) || echo python3)

.PHONY: help orchestrate orchestrate-dry-run apply-agent-results apply-tags dashboard relocate sync-favorites select select-xiaohongshu select-bilibili all

help:
	@echo "WikiHub 导入/导出工作流"
	@echo ""
	@echo "  make orchestrate           - 执行 WikiHub 主控编排流程"
	@echo "  make orchestrate-dry-run   - 预览 WikiHub 主控编排流程"
	@echo "  make apply-agent-results   - 应用 agent 判断结果（隔离/标签）"
	@echo "  make apply-tags            - 将 wikihub-tags.json 同步到 markdown frontmatter"
	@echo "  make relocate              - 根据 ai_tags 自动移动文章到目标 wiki"
	@echo "  make dashboard             - 生成中文注解看板 wikihub-dashboard.md"
	@echo "  make sync-favorites        - 拉取最新收藏夹数据到 wikihub-favorites-cache.json"
	@echo "  make select                - 启动 WikiHub 选择面板（默认端口 7321，冲突时自增）"
	@echo "  make select-xiaohongshu    - 启动 WikiHub 选择面板（默认打开小红书标签）"
	@echo "  make select-bilibili       - 启动 WikiHub 选择面板（默认打开 B 站标签）"
	@echo "  make all                   - 执行导出后的自动化步骤（agent 需先写入 /tmp/wikihub-agent-results.json）"

orchestrate:
	python3 .claude/skills/wikihub-orchestrator/scripts/orchestrate.py

orchestrate-dry-run:
	python3 .claude/skills/wikihub-orchestrator/scripts/orchestrate.py --dry-run

apply-agent-results:
	python3 .claude/skills/wikihub-orchestrator/scripts/apply-agent-results.py

apply-tags:
	python3 .claude/skills/wikihub-orchestrator/scripts/apply-tags.py

dashboard:
	python3 .claude/skills/wikihub-orchestrator/scripts/generate-dashboard.py

relocate:
	python3 .claude/skills/wikihub-orchestrator/scripts/relocate-by-classification.py

sync-favorites:
	$(ORCHESTRATOR_PYTHON) .claude/skills/wikihub-orchestrator/scripts/select_sync_favorites.py

select:
	$(ORCHESTRATOR_PYTHON) .claude/skills/wikihub-orchestrator/scripts/select_agent_helper.py launch --port $(SELECT_PORT)

select-xiaohongshu:
	$(ORCHESTRATOR_PYTHON) .claude/skills/wikihub-orchestrator/scripts/select_agent_helper.py launch --port $(SELECT_PORT) --platform xiaohongshu

select-bilibili:
	$(ORCHESTRATOR_PYTHON) .claude/skills/wikihub-orchestrator/scripts/select_agent_helper.py launch --port $(SELECT_PORT) --platform bilibili

# Agent 工作流：导出后由 agent 读取 /tmp/wikihub-pending.json 并生成 /tmp/wikihub-agent-results.json，
# 然后调用以下步骤完成隔离、标签同步、移动和看板生成。
all: apply-agent-results apply-tags relocate dashboard
