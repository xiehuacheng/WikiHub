#!/usr/bin/env python3
"""
生成 WikiHub 导入/导出看板，展示文章分布、标签统计、当前 wiki 映射和潜在 wiki 建议。
标签保持英文，旁边附加中文注解。
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path.cwd()
EXPORTED_FILE = ROOT / "wikihub-exported.json"
DASHBOARD_FILE = ROOT / "wikihub-dashboard.md"
TAG_CONFIG_FILE = ROOT / "wikihub-tag-config.json"


def load_tag_config() -> dict:
    """加载标签映射配置。"""
    if not TAG_CONFIG_FILE.exists():
        print(f"错误：未找到标签配置文件 {TAG_CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(TAG_CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


TAG_CONFIG = load_tag_config()
TAG_ZH = TAG_CONFIG.get("tag_zh", {})
TAG_TO_WIKI = TAG_CONFIG.get("tag_to_wiki", {})


_ROOT_MARKERS = [
    ".claude/skills/wikihub-orchestrator/wikihub-orchestrator-config.json",
    "wikihub-orchestrator-config.json",
    "Makefile",
]


def ensure_root():
    if not any((ROOT / name).exists() for name in _ROOT_MARKERS):
        print("错误：请在 WikiHub/ 项目根目录下运行此脚本", file=sys.stderr)
        sys.exit(1)


def main():
    ensure_root()
    with open(EXPORTED_FILE, "r", encoding="utf-8") as f:
        exported = json.load(f)

    total = len(exported)
    in_wiki = sum(1 for v in exported.values() if not v["path"].startswith("Unmapped/"))
    unmapped = total - in_wiki

    # Quarantine stats
    quarantined = [r for r in exported.values() if r["path"].startswith("Quarantine/")]

    # 收集所有标签
    all_tags = []
    tag_to_articles = {}
    wiki_to_articles = {}

    for card_id, record in exported.items():
        tags = record.get("ai_tags", [])
        all_tags.extend(tags)

        for tag in tags:
            tag_to_articles.setdefault(tag, []).append(record)

        # 判断所属 wiki
        path = Path(record["path"])
        if path.parts[0] == "Unmapped":
            wiki = "未映射"
        elif path.parts[0] == "Quarantine":
            wiki = "异常隔离"
        else:
            wiki = path.parts[0]
        wiki_to_articles.setdefault(wiki, []).append(record)

    tag_counts = Counter(all_tags)

    lines = []
    lines.append("# WikiHub 导入/导出看板")
    lines.append("")

    if quarantined:
        lines.append("> ⚠️ **内容校验警告**：本次导出发现 {0} 篇文章标题与正文明显不符，已自动隔离到 `Quarantine/`，请人工确认。".format(len(quarantined)))
        lines.append("")

    lines.append(f"- **总文章数**：{total}")
    lines.append(f"- **已进入 wiki**：{in_wiki}")
    lines.append(f"- **未映射（Unmapped）**：{unmapped}")
    if quarantined:
        lines.append(f"- **异常隔离（Quarantine）**：{len(quarantined)}")
    lines.append("")

    # 当前 wiki 分布
    lines.append("## 当前 Wiki 分布")
    lines.append("")
    for wiki, articles in sorted(wiki_to_articles.items()):
        lines.append(f"- **{wiki}**：{len(articles)} 篇")
    lines.append("")

    # 主题标签分布
    lines.append("## 主题标签分布")
    lines.append("")
    lines.append("| 标签 | 中文注解 | 文章数 | 建议创建为 |")
    lines.append("|------|----------|--------|------------|")

    for tag, count in tag_counts.most_common():
        zh = TAG_ZH.get(tag, "")
        suggestion = TAG_TO_WIKI.get(tag, "")
        lines.append(f"| {tag} | {zh} | {count} | {suggestion} |")
    lines.append("")

    # 潜在可创建的 wiki
    lines.append("## 潜在可创建的 Wiki")
    lines.append("")
    lines.append("基于当前标签聚合，以下主题已具备单独建 wiki 的潜力：")
    lines.append("")

    potential_wikis = [
        ("AI编程_wiki", "AI 编程、Claude Code、Codex", ["ai-coding", "claude-code", "codex"]),
        ("AI智能体_wiki", "AI Agent、Agent 生态", ["ai-agent", "agent-ecosystem"]),
        ("效率_wiki", "效率提升、专注力、习惯、拖延", ["productivity", "focus", "habits", "todo", "time-management", "procrastination"]),
        ("个人成长_wiki", "个人成长、激励、反思、自我认知", ["personal-growth", "motivation", "reflection", "self-awareness"]),
        ("心理健康_wiki", "心理健康、拖延、ADHD、心理学", ["mental-health", "procrastination", "adhd", "psychology"]),
        ("人际关系_wiki", "人际关系、沟通表达、情绪情感", ["relationships", "communication", "emotions"]),
        ("工具_wiki", "工具软件、Notion、JetBrains、WordPress", ["tools", "notion", "jetbrains", "wordpress"]),
        ("学习_wiki", "学习方法、考试备考、教育", ["study", "exam-prep", "learning", "education"]),
        ("健康_wiki", "健康、睡眠", ["health", "sleep"]),
    ]

    for wiki_name, wiki_desc, wiki_tags in potential_wikis:
        articles = set()
        for tag in wiki_tags:
            for record in tag_to_articles.get(tag, []):
                articles.add(record["path"])
        if len(articles) >= 3:
            lines.append(f"- **{wiki_name}**（{wiki_desc}）：约 {len(articles)} 篇相关文章")
    lines.append("")

    # Unmapped 文章标签分布
    lines.append("## 未映射文章标签分布")
    lines.append("")
    unmapped_tags = []
    for record in exported.values():
        if record["path"].startswith("Unmapped/"):
            unmapped_tags.extend(record.get("ai_tags", []))

    unmapped_counts = Counter(unmapped_tags)
    for tag, count in unmapped_counts.most_common():
        zh = TAG_ZH.get(tag, "")
        lines.append(f"- **{tag}**（{zh}）：{count} 篇")
    lines.append("")

    # Quarantine 区块
    if quarantined:
        lines.append("## 异常隔离（Quarantine）")
        lines.append("")
        lines.append("以下文章标题与正文内容明显不符，已被自动隔离，请人工确认：")
        lines.append("")
        lines.append("| 文件名 | 标题 | 隔离原因 |")
        lines.append("|--------|------|----------|")
        for record in quarantined:
            filename = Path(record["path"]).name
            title = record.get("title", "")
            reason = record.get("quarantine_reason", "")
            lines.append(f"| {filename} | {title} | {reason} |")
        lines.append("")

    lines.append("")

    DASHBOARD_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"看板已生成：{DASHBOARD_FILE}")


if __name__ == "__main__":
    main()
