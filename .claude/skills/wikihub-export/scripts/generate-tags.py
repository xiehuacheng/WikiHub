#!/usr/bin/env python3
"""Generate wikihub-tags.json from manual AI classification."""

import json
from pathlib import Path

ROOT = Path.cwd()

TAGS = {
    # DL/AI articles
    "7468554660408722335": ["ai", "rag", "llm", "research"],
    "7468552281848284088": ["ai", "rag", "llm", "research"],
    "7458264110363315007": ["ai", "claude-code", "ai-coding", "tutorial"],
    "7456368137215151112": ["ai", "skills", "reading", "agent-ecosystem"],
    "7454529827769417733": ["programming", "concurrency", "tutorial", "computer-science"],
    "7453733423090238686": ["ai", "tech-writing", "llm", "tools"],
    "7453465859713927301": ["ai", "industry", "nvidia", "career"],
    "7452703532769085418": ["ai", "claude-code", "skills", "ai-coding"],
    "7452703495603359312": ["ai", "claude-code", "ai-coding", "productivity"],
    "7452411520765395113": ["ai", "ai-agent", "industry", "anthropic"],
    "7451656399219592836": ["ai", "claude-code", "industry", "startup"],
    "7451627554479276778": ["ai", "claude-code", "ai-agent", "learning"],
    "7449478205246803420": ["ai", "ai-agent", "future-of-work", "industry"],
    "7448415293937814213": ["ai", "claude-code", "ai-coding", "entrepreneurship"],
    "7448296909443173287": ["ai", "llm", "openai", "industry"],
    "7448134840534172630": ["ai", "ai-agent", "skills", "agent-ecosystem"],
    "7448134825979940207": ["ai", "ai-agent", "product-review", "tools"],
    "7448134808321917654": ["ai", "claude-code", "skills", "ai-coding"],
    "7448134651639498497": ["ai", "llm", "knowledge-management", "tools"],
    "7447207749697405620": ["ai", "llm", "open-source", "deepseek"],
    "7446579795464293350": ["ai", "claude-code", "codex", "ai-coding"],
    "7446579752963411902": ["ai", "claude-code", "industry", "llm"],
    "7446579495898712360": ["ai", "claude-code", "ai-coding", "github"],
    "7446579450054969527": ["ai", "ai-agent", "startup", "workflow"],
    "7446579365283892696": ["ai", "claude-code", "ai-agent", "tutorial"],
    "7446579364935762544": ["ai", "ai-agent", "open-source", "bytedance"],
    "7446579364877044902": ["ai", "ai-coding", "memory", "github"],
    "7446579364700882906": ["ai", "claude-code", "ai-coding", "wechat-mini-program"],
    "7446571091645958944": ["ai", "ai-agent", "open-source", "github"],
    "7427693133216875108": ["machine-learning", "data-engineering", "tutorial"],
    "7427049359209923457": ["ai", "ai-agent", "llm", "tutorial"],
    "7426594789660822601": ["ai", "ai-agent", "research", "industry"],
    "7392417712212806171": ["ai", "llm", "education", "hands-on"],

    # Personal growth / life
    "7456076095020862225": ["personal-growth", "life", "psychology"],
    "7455367886975010562": ["relationships", "emotions", "life"],
    "7452128694291663736": ["relationships", "communication", "personal-growth"],
    "7451627638533130316": ["relationships", "emotions", "life"],
    "7448824314633126662": ["relationships", "emotions", "mental-health"],
    "7447467269845681418": ["personal-growth", "career", "life"],
    "7446579450365346879": ["personal-growth", "mental-health", "life", "experiment"],
    "7446579449924947820": ["unknown"],
    "7446579366277941270": ["personal-growth", "life", "reflection"],
    "7446579364910596500": ["communication", "procrastination", "personal-growth"],
    "7446579364826713580": ["personal-growth", "mental-health", "habits"],
    "7446579364805741403": ["personal-growth", "motivation", "life"],
    "7446579364738630382": ["digital-minimalism", "procrastination", "personal-growth"],
    "7446579364679909868": ["reading", "personal-growth", "habits"],
    "7446579364650551982": ["relationships", "emotions", "personal-growth"],
    "7446578850747649860": ["procrastination", "personal-growth", "mental-health"],
    "7446578809848988711": ["procrastination", "mental-health", "personal-growth"],
    "7446578808099964956": ["relationships", "emotions", "life"],
    "7446578808087381869": ["personal-growth", "psychology", "life"],
    "7446578808078993029": ["personal-growth", "self-awareness", "life"],
    "7446578808049632946": ["personal-growth", "reflection", "year-end"],
    "7446578807974136962": ["study", "focus", "exam-prep"],
    "7446578807835724010": ["mental-health", "personal-growth", "life"],
    "7446578549596622232": ["unknown"],
    "7410831779155674118": ["productivity", "focus", "habits"],
    "7410831726391329611": ["productivity", "study", "motivation"],
    "7409572398099333963": ["reflection", "year-end", "life"],
    "7408301862492832044": ["health", "sleep", "productivity"],
    "7398858668319444514": ["communication", "personal-growth", "life"],
    "7398133354672947256": ["productivity", "todo", "habits"],
    "7398133237454736834": ["digital-minimalism", "focus", "personal-growth"],
    "7397704235875303549": ["personal-growth", "life", "philosophy"],
    "7397419990908931624": ["personal-growth", "motivation", "life"],
    "7397402821303207802": ["study", "focus", "health"],
    "7397188982821358671": ["focus", "productivity", "study"],
    "7396991172654139563": ["productivity", "habits", "time-management"],
    "7396990939857682727": ["productivity", "focus", "habits"],
    "7396493021207857546": ["procrastination", "mental-health", "personal-growth"],
    "7395874045972975331": ["life", "gamification", "personal-growth"],
    "7395584593560079960": ["productivity", "year-end", "life"],
    "7395583037972418184": ["productivity", "habits", "year-end"],
    "7395582699202676411": ["adhd", "focus", "productivity"],
    "7395546754734623351": ["communication", "relationships", "personal-growth"],
    "7392414183364493753": ["study", "health", "productivity"],
    "7392413785568314853": ["productivity", "todo", "personal-growth"],
    "7391801798719179422": ["productivity", "weekly-review", "reflection"],
    "7391801413526884329": ["productivity", "focus", "mac-apps"],
    "7393216479396627700": ["study", "focus", "motivation"],

    # Tools / tutorials
    "7456316075534191207": ["tools", "apple-id", "tutorial", "shopping"],
    "7395993593296456646": ["tools", "notion", "productivity"],
    "7395445779202049183": ["tools", "jetbrains", "tutorial"],
    "7395210165764490455": ["tools", "notion", "email"],
    "7207668425718498143": ["tools", "wordpress", "tutorial", "web-dev"],
    "7393691684011249638": ["music", "singing", "tutorial"],
}


def ensure_root():
    # WikiHub 项目根目录应至少包含一个导出配置文件
    if not (ROOT / "bilibili-export-config.json").exists() and not (ROOT / "cubox-export-config.json").exists():
        print("错误：请在 WikiHub/ 项目根目录下运行此脚本", file=sys.stderr)
        sys.exit(1)


def main():
    ensure_root()
    exported = json.load(open("wikihub-exported.json"))
    # Only keep tags for existing card_ids
    tags = {cid: TAGS[cid] for cid in exported if cid in TAGS}

    # Warn about missing
    missing = [cid for cid in exported if cid not in TAGS]
    if missing:
        print(f"Warning: {len(missing)} cards without tags")
        for cid in missing:
            print(f"  - {cid}: {exported[cid]['path']}")

    Path("wikihub-tags.json").write_text(
        json.dumps(tags, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote tags for {len(tags)} cards to wikihub-tags.json")


if __name__ == "__main__":
    main()
