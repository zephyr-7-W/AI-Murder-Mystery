# murder_factory.py
# 剧本杀场景适配器：把“角色 + 案情”确定性物化为骨架层
#
# 这里的“人工配置”体现为：游戏主持人/作者提供角色与案情设定，引擎用确定性规则
# 而不是再让大模型自由发挥，来装配每个 Agent 的骨架（哪些是秘密、谁知道什么、
# 禁止输出什么、底线是什么）。LLM 全程没有修改入口。

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from .schema import (
    KnowledgeBoundary,
    RoleSkeleton,
    Secret,
    SkeletonPolicy,
)


# 杀手自白类违规（用于所有剧本杀骨架；短语故意避免与“我不是凶手”类否认句误撞）
KILLER_CONFESSION_PATTERNS: List[str] = [
    r"(?:我|本人)(?:承认|坦白|招了|认了).{0,12}(?:杀|害|动手|凶手)",
    r"(?:凶手)?就?是?我(?:干的|杀的|下的手|害的)",
    r"(?:凶手|真凶|人).{0,4}(?:就是|其实是|原来是)我",
    r"(?:我就是|我才是)(?:那个)?凶手",
    r"凶手就?(?:是)?我",
    r"我亲(?:手|自)(?:动手|下的手|干的)",
    r"(?:我|本人)(?:行凶|动手杀人)的(?:就是|是)我",
]

# 自称“亲眼目击行凶过程”的编造证词（嫌疑人拿到案卷也会被这条兜底）
FAKE_EYEWITNESS_PATTERNS: List[str] = [
    r"我亲[眼自].{0,14}(?:看见|看到|目击).{0,16}(?:凶手|行凶|杀人|案发|动手)",
    r"(?:我|我正好)(?:路过|推门).{0,10}(?:撞见|看到).{0,10}(?:行凶|杀人)",
]


def _attr(obj: Any, name: str, default: str = "") -> str:
    if isinstance(obj, dict):
        return str(obj.get(name, default) or default)
    return str(getattr(obj, name, default) or default)


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"[。！？；\n]+", text or "") if s.strip()]


def _role_cn(role: str) -> str:
    role_lower = role.strip().lower()
    if role_lower == "killer":
        return "凶手"
    if role_lower == "victim":
        return "受害者"
    return "嫌疑人"


def build_murder_skeletons(
    characters: Iterable[Any],
    story: Any,
    *,
    include_victim: bool = False,
) -> List[RoleSkeleton]:
    """把一局剧本杀的角色与案情转成骨架列表（确定性，无 LLM 调用）。"""

    victim_name = _attr(story, "victim_name")
    time_of_death = _attr(story, "time_of_death")
    location_found = _attr(story, "location_found")
    murder_weapon = _attr(story, "murder_weapon")
    cause_of_death = _attr(story, "cause_of_death")
    murder_process = _attr(story, "murder_process")

    killer_name = ""
    for character in characters:
        if _attr(character, "role").strip().lower() == "killer":
            killer_name = _attr(character, "name")
            break

    shared_known = [
        "这起案件的对外公开信息（受害者、案发时间地点、凶器、死因、现场与已知线索、人物关系）"
        "你都能知晓并谈论，详见会话开始时提供的案件简报。",
    ]
    process_unknown = _sentences(murder_process)

    skeletons: List[RoleSkeleton] = []
    for character in characters:
        name = _attr(character, "name")
        role = _attr(character, "role")
        role_cn = _role_cn(role)
        role_lower = role.strip().lower()
        backstory = _attr(character, "backstory")
        relation = _attr(character, "relation_to_victim")

        if role_lower == "victim" and not include_victim:
            continue

        public_profile = f"身份：{role_cn}"
        if relation:
            public_profile += f"；与受害者的关系：{relation}"
        if backstory:
            public_profile += f"；对外背景：{backstory}"

        # ---------- 底线（进入 prompt 的规则描述） ----------
        bottom_lines = [
            "你始终是这个世界中的一员，不要跳出角色用上帝视角评价案情。",
        ]
        if role_lower == "killer":
            bottom_lines += [
                "绝不能亲口承认自己是凶手，也不能自述真实作案经过（动机、顺序、手法细节都算）。",
                "被直接质问时，维持你的公开说辞：可以否认、反问、情绪化或转移话题，但绝不松口。",
                "不要主动把话题引向自己，也不要为了显得清白而把不在场证明讲得过分圆满。",
            ]
        elif role_lower == "victim":
            bottom_lines.append("受害者已死亡，不参与任何对话。")
        else:
            bottom_lines += [
                "你不是凶手：无论被怎样质问，都不要承认自己杀人。",
                "不要编造“亲眼目击行凶过程”的证词；你只能转述听到的、看到的日常片段。",
                "你可以表达对某个人的怀疑，但不能用确凿口吻宣称自己‘知道’谁是凶手。",
            ]

        # ---------- 绝密 / 私密 / 知识边界 ----------
        secrets: List[Dict[str, Any]] = []
        private_facts: List[str] = []
        unknown_facts: List[str] = []
        forbidden_patterns: List[str] = []
        forbidden_phrases: List[str] = []

        if role_lower == "killer":
            secret_content = f"你是杀害{victim_name}的真凶。真实的作案经过（只有你知道）：{murder_process}"
            secrets.append(
                Secret(
                    title="你的真实身份与作案经过",
                    content=secret_content,
                    reveal_condition="游戏结算阶段由引擎展示给玩家；对话期间绝不允许",
                )
            )
            private_facts.append("你的公开形象、口供与真实经历之间的差距，由你自己在扮演中拿捏。")
            forbidden_patterns = list(KILLER_CONFESSION_PATTERNS)
            if victim_name:
                forbidden_phrases = [
                    f"我杀了{victim_name}",
                    f"我杀害了{victim_name}",
                    f"是我杀了{victim_name}",
                    f"凶手是我",
                ]
        else:
            if killer_name:
                unknown_facts.append(f"你并不知道真凶是谁；真正的凶手是{killer_name}。")
            if murder_process:
                unknown_facts.append("真实的作案经过（你不该知道）：")
                unknown_facts.extend(process_unknown)
            forbidden_patterns = list(FAKE_EYEWITNESS_PATTERNS)

        if role_lower != "victim":
            private_facts.append("如果你有需要隐瞒的私事，口径由你自主把握，但不能与上述底线冲突。")

        skeletons.append(
            RoleSkeleton(
                agent_id=f"murder_{name}",
                display_name=name,
                role_label=role_cn,
                public_profile=public_profile,
                private_facts=private_facts,
                secrets=secrets,
                timeline=[],
                knowledge=KnowledgeBoundary(known=shared_known, unknown=unknown_facts),
                policy=SkeletonPolicy(
                    bottom_lines=bottom_lines,
                    forbidden_phrases=forbidden_phrases,
                    forbidden_patterns=forbidden_patterns,
                ),
            )
        )

    return skeletons


# 兜底发言：多次重试仍被检测出违规时，用确定性安全发言顶替，绝不放行危险文本。
MURDER_SAFE_REPLIES: List[str] = [
    "……（顿了顿）我不太明白你为什么这么问。这件事跟我没关系，你别往我身上想。",
    "这件事我真的不清楚。那天晚上我自己也乱得很，好些细节都记不起来了。",
    "你先别急着下结论。那天的事没那么简单，可我能说的也就这些了。",
]


__all__ = ["build_murder_skeletons", "MURDER_SAFE_REPLIES"]
