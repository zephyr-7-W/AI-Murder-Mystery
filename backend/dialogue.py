# dialogue.py
# 对话 / 扮演引擎（原 main.py 中与“如何说话、如何推进对话”有关的纯逻辑）
#
# 拆分目的：
#   - main.py 只保留 WS 分发、状态序列化、会话持久化与动作路由；
#   - 这里沉淀可单测的“角色回答 / AI 代问 / 提示 / 现场调查”逻辑；
#   - 所有大模型调用统一走 llm_util.raw_invoke（含超时、重试、耗时日志）。
#
# 与骨架层的关系：
#   - RoleSkeleton 是只读的“静态骨架”，本模块只能读取并渲染，不能改写；
#   - 骨架审查（LeakGuard / constrained_answer）在本模块被调用，保证动态对话层
#     输出在放行给玩家前过一遍“防泄露 + 分级重写”闭环。

from __future__ import annotations

import random
from typing import Any, Iterable

from config import llm  # noqa: F401  保留引用，便于调试/替换
from coach import candidate_questions
from langchain_core.messages import HumanMessage, SystemMessage
from llm_util import available, raw_invoke
from oracle import (
    question_is_substantive,
    relevance_score,
    touches_reveal,
)
from models import Character, StoryDetails
from role_skeleton.murder_factory import MURDER_SAFE_REPLIES
from role_skeleton.prompt import render_skeleton_block
from role_skeleton.runner import constrained_answer




def _normalize_message(msg: Any) -> dict:
    """把消息对象规整成 {type, content} 字典（本模块自用，不参与序列化 seq/ts）。"""
    if isinstance(msg, dict):
        return {"type": str(msg.get("type") or "ai"), "content": str(msg.get("content") or "")}
    if hasattr(msg, "content"):
        kind = getattr(msg, "type", None)
        return {
            "type": "ai" if str(kind or "ai").lower() in {"ai", "assistant"} else "human",
            "content": str(getattr(msg, "content", "")),
        }
    return {"type": "ai", "content": str(msg)}

def _killer_index(state: dict[str, Any]) -> int | None:
    if not state.get("characters"):
        return None
    for index, character in enumerate(state["characters"]):
        if str(character.role).strip().lower() == "killer":
            return index
    return None


def _suspect_indexes(state: dict[str, Any]) -> list[int]:
    """按角色顺序返回所有非受害者（即嫌疑人）在 characters 中的下标。"""
    return [
        index
        for index, character in enumerate(state.get("characters", []))
        if str(character.role).strip().lower() != "victim"
    ]


def _find_skeleton(skeletons, character):
    """按姓名在会话骨架列表里找到对应角色骨架；找不到返回 None 走旧逻辑。"""
    if not skeletons:
        return None
    target_name = getattr(character, "name", None)
    if target_name is None and isinstance(character, dict):
        target_name = character.get("name")
    for skeleton in skeletons:
        if skeleton.display_name == target_name:
            return skeleton
    return None


def _build_victim_report(state: dict[str, Any]) -> str:
    """生成一份受害者调查简报：现场、死前经历与身边人转述，供玩家破案参考。"""
    story = state.get("story_details")
    if not isinstance(story, StoryDetails):
        return "（暂无死者信息，请先开始新的一局游戏。）"
    characters = state.get("characters") or []
    victim = next((c for c in characters if str(c.role).strip().lower() == "victim"), None)
    killer = next((c for c in characters if str(c.role).strip().lower() == "killer"), None)

    if not available():
        lines = [
            "【死因与死亡时间】",
            story.cause_of_death + "，推测死亡时间约在 " + story.time_of_death + "。",
            "发现地点：" + story.location_found,
            "现场情况：" + story.crime_scene_details,
            "",
            "【目前掌握的线索】",
            story.initial_clues,
            "",
            "【人物关系】",
            story.npc_brief,
        ]
        return "\n".join(lines)

    parts = []
    parts.append("你是一位推理小说里的档案整理者。请为玩家整理一份受害者调查简报，帮助玩家破案。")
    parts.append("简报要像卷宗摘录：语气克制、客观，绝不能有审讯口吻，也不能替玩家下结论。")
    parts.append("")
    if victim is not None:
        parts.append("受害者资料：")
        parts.append("姓名：" + victim.name)
        parts.append("背景：" + victim.backstory)
        parts.append("")
    parts.append("案件信息：")
    parts.append("- 受害者：" + story.victim_name)
    parts.append("- 死亡时间：" + story.time_of_death)
    parts.append("- 发现地点：" + story.location_found)
    parts.append("- 作案工具：" + story.murder_weapon)
    parts.append("- 死因：" + story.cause_of_death)
    parts.append("- 现场情况：" + story.crime_scene_details)
    parts.append("- 目击与最后目击：" + story.witnesses)
    parts.append("- 初步线索：" + story.initial_clues)
    parts.append("- 人物关系：" + story.npc_brief)
    if killer is not None:
        parts.append("")
        parts.append("（内部已知真相，仅供你保证线索前后一致，绝对禁止写入简报：真凶是 " + killer.name + "）")
    parts.append("")
    parts.append("请按下述结构输出简体中文简报：")
    parts.append("【死因与死亡时间】")
    parts.append("写死亡原因、推测死亡时间，以及能用来核对时间线的现场细节。")
    parts.append("【死前的最后经历】")
    parts.append("结合现场痕迹、遗物与他人的转述，推断死者死前最后几个小时的活动：见过谁、去过哪、发生过什么。")
    parts.append("【身边人的只言片语】")
    parts.append("转述与死者关系较近的人留下的回忆与说法，不要点名，用死者的妻子、死者的好友这类关系代称。")
    parts.append("【值得留意的疑点】")
    parts.append("列出 3 到 5 个供玩家之后与其他角色聊天时核实的疑点，例如时间线矛盾、不该出现的痕迹、被刻意掩盖的小事。")
    parts.append("")
    parts.append("硬性要求：")
    parts.append("1. 整篇简报绝不能出现真凶的名字，也不能暗示、排序或指向某一个角色更可疑；")
    parts.append("2. 线索必须真实、有用，能帮助玩家通过与角色聊天逐步推理；")
    parts.append("3. 简报不能点名任何人的作案嫌疑，措辞要像普通卷宗摘录；")
    parts.append("4. 只用简体中文输出，人名除外。")
    system_prompt = "\n".join(parts)
    try:
        result = raw_invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content="请整理这份受害者调查简报。"),
        ])
        return str(result.content).strip() or "（暂时没有更多关于死者的信息，请换个方向调查。）"
    except Exception as exc:  # 模型异常时退回确定性兜底，保证受害者面板仍可看
        print(f"[受害者简报] LLM 调用失败：{exc}")
        return "（模型暂时不可用。可从现有案情面板查看：死因与死亡时间在“案情速览”，现场与初步线索会随调查陆续解锁。）"


def _coach_anchor(messages, character_name: str):
    """从会话里提取“最近一句 NPC 的话 / 玩家的话”，给目标排序与措辞当锚。"""
    npc_last = ""
    player_last = ""
    for raw in messages:
        msg = _normalize_message(raw)
        content = str(msg.get("content") or "")
        if msg.get("type") == "human":
            player_last = content
            continue
        prefix = f"{character_name}:"
        if content.startswith(prefix):
            npc_last = content[len(prefix):].strip()
        elif not npc_last:
            npc_last = content
    return npc_last, player_last


def _coach_llm_question(
    character: Character,
    story: StoryDetails,
    messages: list[dict],
    skeleton=None,
    exposed_texts: list[str] | None = None,
    extra_hint: str = "",
) -> str:
    """让 LLM 以“玩家口吻”想一句自然的追问。

    给模型的信息只包括：玩家当前能看到的案情 + 近期对话 + 本角色已松口的可见内容，
    以及角色骨架里的【可公开人设】（绝不把秘密本体 / 底线清单喂给它，避免帮玩家透视答案）。
    """
    if not available():
        return ""
    recent = messages[-8:] if len(messages) > 8 else messages
    conv = "\n".join(
        f"{'玩家' if m.get('type') == 'human' else '角色'}: {m.get('content', '')}"
        for m in map(_normalize_message, recent)
    ) or "（暂无对话记录）"

    public_persona = ""
    if skeleton is not None:
        public_persona = str(getattr(skeleton, "public_profile", "") or "").strip()

    visible_facts = ""
    if story is not None:
        visible_facts = "\n".join(
            [
                f"- 受害者：{story.victim_name}",
                f"- 死亡时间：{story.time_of_death}",
                f"- 发现地点：{story.location_found}",
                f"- 作案工具：{story.murder_weapon}",
                f"- 现场情况：{story.crime_scene_details}",
                f"- 公开线索：{story.initial_clues}",
                f"- 人物关系：{story.npc_brief}",
            ]
        )
    revealed_block = "\n".join(f"- {r}" for r in (exposed_texts or [])) or "（暂无）"

    prompt = f"""
你是一个推理游戏里的“聊天助手”，站在玩家一边，帮玩家想一句自然的搭话/追问。你不是任何角色，不要替玩家下结论。

角色资料（可公开人设，玩家也能从档案看到）：
- 姓名：{character.name}
- 身份：{character.role}
- 关系：{character.relation_to_victim}
- 背景：{character.backstory}
{("骨架公开人设：" + public_persona) if public_persona else ""}

案件公开信息（玩家目前可见）：
{visible_facts}

这位角色已经松口、玩家已知道的内容：
{revealed_block}

近期对话（最后几句）：
{conv}

{("额外提示：" + extra_hint) if extra_hint else ""}

要求（很重要）：
1. 必须接着“近期对话”的话头自然往下说，像唠家常一样，不要突然切换成查户口式提问；
2. 只输出一句玩家可以直接说出口的话，用口语、用“你/我”，控制在 60 字以内；
3. 话题可以往玩家还没拿到的细节引（当夜行踪、目击、某样东西、人物关系都行），但不要把答案直接塞进问题里；
4. 不要出现“案发时你在哪里”“你是不是凶手”“你有不在场证明吗”这类审讯句；
5. 不要引用、暗示或打探上面“骨架公开人设”之外的私密设定；对方若明显不愿多谈，就软一点，绕个弯；
6. 只用简体中文输出，不要引号包裹、不要任何解释。

只输出那一句话。
"""
    try:
        result = raw_invoke([SystemMessage(content=prompt)])
        question = str(result.content or "").strip().strip('“”"\'')
        return question[:140]
    except Exception as exc:
        print(f"[AI代问] LLM 措辞失败：{exc}")
        return ""


def _compose_auto_questions(
    character: Character,
    story: StoryDetails,
    messages: list[dict],
    skeleton=None,
    locked_items=None,
    exposed_texts: list[str] | None = None,
    asked_questions: list[str] | None = None,
    extra_hint: str = "",
) -> list[str]:
    """生成“AI 帮我提问”候选问法（由 main 的 auto_ask 做 oracle 预检放行）。"""
    npc_last, player_last = _coach_anchor(messages, character.name)
    llm_questions: list[str] = []
    if available():
        first = _coach_llm_question(
            character, story, messages, skeleton=skeleton,
            exposed_texts=exposed_texts, extra_hint=extra_hint,
        )
        if first:
            llm_questions.append(first)
    return candidate_questions(
        character=character,
        story=story,
        npc_last=npc_last,
        player_last=player_last,
        locked=locked_items or [],
        llm_questions=llm_questions,
        avoid=asked_questions or [],
    )


def _exposed_reveals_ordered(oracle_items, matched):
    """把刚放行的那条揭示排最前，其余保持原有顺序。

    让 _answer_as_character 的离线兜底与 LLM 提示都优先接上“玩家/代问刚问出来
    的最新一条”，而不是总复读最早暴露的那条。
    """
    texts = []
    matched_id = getattr(matched, "id", None) if matched is not None else None
    if matched is not None and getattr(matched, "text", ""):
        texts.append(matched.text)
    for item in oracle_items:
        if not item.exposed or not item.text:
            continue
        if item.id == matched_id:
            continue
        texts.append(item.text)
    return texts


def _reset_chat_progress(session_state, name: str) -> None:
    progress = session_state.setdefault("_chat_progress", {})
    progress.pop(name, None)


def _bump_chat_progress(session_state, name, question, locked, story, characters):
    """多轮渐进解锁：单句没直接命中时，把“沾边提问”累计到该角色名下。

    返回 (item, mode) 或 None：
      mode="touch" -> 两轮都问中同一条线索的边，放行；
      mode="depth" -> 实质性聊满 3 轮仍没解锁，挑最贴近当前话题的一条放行。
    纯寒暄（hi/天气）不含案情话题/实体信号，不计入进度，不会触发解锁。
    """
    if not question.strip() or not locked or story is None:
        return None
    if not question_is_substantive(question, story, characters):
        return None
    progress = session_state.setdefault("_chat_progress", {}).setdefault(
        name, {"sub": 0, "touches": {}}
    )
    progress["sub"] += 1
    for item in locked:
        if touches_reveal(question, str(item.text or ""), story, characters):
            progress["touches"][item.id] = progress["touches"].get(item.id, 0) + 1

    best = None
    best_score = -1
    for item in locked:
        if progress["touches"].get(item.id, 0) >= 2:
            score = relevance_score(question, str(item.text or ""), story, characters)
            if score > best_score:
                best_score = score
                best = item
    if best is not None:
        return best, "touch"
    if progress["sub"] >= 3:
        fallback = None
        fallback_score = -1
        for item in locked:
            score = relevance_score(question, str(item.text or ""), story, characters)
            if score > fallback_score:
                fallback_score = score
                fallback = item
        return (fallback or locked[0]), "depth"
    return None


# 玩家发送消息后，调用 LLM 生成 NPC 角色回复：
# system prompt 约束NPC行为：自然聊天、可以说谎、不主动自爆凶手身份，含蓄透露线索。


def _answer_as_character(
    character: Character,
    story: StoryDetails,
    question: str,
    skeleton=None,
    exposed_reveals: list[str] | None = None,
    just_revealed: str | None = None,
) -> str:
    """生成 NPC 回复。

    exposed_reveals：该角色本局已被真相 oracle 放行的细节文本。未被放行的
    卷宗细节不会进入扮演模型上下文，闲聊不会一次倒出全部线索。
    """
    revealed = [r for r in (exposed_reveals or []) if r and r.strip()]

    # 离线兜底：问中要害并解锁新内容 -> 松口一小段；只是闲聊/没问中新点 -> 含糊带过，
    # 绝不倒卷宗，也不复读已经给过的旧线索。
    if not available():
        fresh = str(just_revealed or "").strip()
        if fresh:
            lead = random.choice([
                f"（{character.name}顿了顿，声音压低了点）",
                f"{character.name}往门口瞟了一眼，含糊地说：",
                f"（{character.name}搓了搓手，像是下了决心）",
            ])
            # 揭示文本常写成“X说/承认/坚持说……”，口头复述时剥掉自述前缀更自然
            text = fresh
            for pfx in (
                f"{character.name}说",
                f"{character.name}坚持说",
                f"{character.name}则坚持说",
                f"{character.name}承认他",
                f"{character.name}承认她",
                f"{character.name}承认",
                f"{character.name}提到",
                f"{character.name}也提到",
                f"{character.name}还提到",
                f"{character.name}记得",
                f"{character.name}解释",
                f"{character.name}最后说",
            ):
                if text.startswith(pfx):
                    text = text[len(pfx):].lstrip("，,：:、 ")
                    break
            if not text:
                text = fresh
            if len(text) > 90:
                text = text[:90] + "……"
            return lead + f"“{text}”"
        return random.choice(MURDER_SAFE_REPLIES)

    system_prompt = f"""
你扮演一个人：
- 名称：{character.name}
- 角色：{character.role}
- 背景：{character.backstory}

案件公开信息（所有在场的人都知道的层面）：
- 受害者：{story.victim_name}
- 死亡时间：{story.time_of_death}
- 发现地点：{story.location_found}
- 作案工具：{story.murder_weapon}
- 死因：{story.cause_of_death}
- 公开的人物关系：{story.npc_brief}

要求（这是小说式的闲聊，不是审讯）：
1. 用真实自然的聊天语气回应，像熟人闲聊、回忆或感叹，而不是供述或接受盘问；
2. 玩家只是随口聊聊（问好、寒暄）时，可以反问、岔开话题、流露情绪，不要把卷宗细节倒出来；
3. 只有当玩家具体问到了某件事（时间、地点、人物、物品、现场细节）时，才顺着对方的话题多说一点；如果玩家是接着你上一句话追问，要顺着刚才说过的话往下接话（承认、补充或圆谎都行），别表现得像头一次听到这个问题；
4. 不要主动承认自己是凶手，也不要主动交代决定性破绽；
5. 可以隐瞒或说谎，但要说谎得自然、自洽；
6. 除人名外，一律使用简体中文。

玩家问题：{question}
"""
    if revealed:
        revealed_block = "\n".join(f"- {r}" for r in revealed)
        system_prompt += f"""

本局你向这位玩家松口过 / 正在被追问的细节如下。被问到不要否认自己刚说过的话，
但要用闲聊口吻自然带出，不要逐字背诵整段，也不要因为提到其中一条就把其它没问的也说出来：
{revealed_block}
"""

    # 骨架层只读注入：动态对话层永远看不到可写对象，只有渲染文本
    if skeleton is not None:
        system_prompt = render_skeleton_block(skeleton) + "\n\n" + system_prompt

    def _raw_generate(extra_instruction):
        try:
            messages = [SystemMessage(content=system_prompt)]
            if extra_instruction:
                messages.append(SystemMessage(content=extra_instruction))
            messages.append(HumanMessage(content="以聊天的口吻自然地回应刚才那句话，就像小说里的人物随口接话一样，不需要条理清晰地交代。"))
            result = raw_invoke(messages)
            text = str(result.content).strip()
            # 模型返回空也兜底，保证 NPC 一定回话
            return text if text else random.choice(MURDER_SAFE_REPLIES)
        except Exception as exc:  # 模型超时/报错时兜底，不让连接断掉、不出现“无回应”
            print(f"[对话] LLM 调用失败：{exc}")
            return random.choice(MURDER_SAFE_REPLIES)

    if skeleton is None:
        return _raw_generate(None)

    def _fallback():
        return random.choice(MURDER_SAFE_REPLIES)

    final_text, audit_rounds = constrained_answer(
        skeleton, _raw_generate, fallback=_fallback, max_retry=2
    )
    for record in audit_rounds:
        if not record.clean or record.used_fallback:
            print(
                f"[骨架审查] {character.name} round={record.attempt + 1} "
                f"sources={record.sources} clean={record.clean} "
                f"fallback={record.used_fallback}"
            )
    return final_text



# 从历史消息里统计已经聊过的嫌疑人姓名（按“姓名:”开头识别），供提示系统使用


def _talked_names(state: dict[str, Any]) -> set[str]:
    names = {getattr(c, "name", "") for c in state.get("characters", []) if getattr(c, "name", "")}
    talked: set[str] = set()
    for raw in state.get("messages", []):
        content = str(raw.get("content") if isinstance(raw, dict) else getattr(raw, "content", "") or "")
        for name in names:
            if content.startswith(name + ":"):
                talked.add(name)
                break
    return talked


def _killer_name(state: dict[str, Any]) -> str:
    killer_index = _killer_index(state)
    if killer_index is None:
        return ""
    return state["characters"][killer_index].name


def _story_prompt_text(state: dict[str, Any]) -> str:
    """把案情拼成一段脱敏上下文（真凶姓名隐藏），供调查/提示的 LLM 提示词使用。"""
    story = state.get("story_details")
    if story is None:
        return ""
    sections = [
        ("受害者", story.victim_name),
        ("死亡时间", story.time_of_death),
        ("发现地点", story.location_found),
        ("作案工具", story.murder_weapon),
        ("死因", story.cause_of_death),
        ("现场情况", story.crime_scene_details),
        ("目击信息", story.witnesses),
        ("初步线索", story.initial_clues),
        ("人物关系", story.npc_brief),
        ("案件经过", story.murder_process),
    ]
    joined = "\n".join(f"- {key}：{value}" for key, value in sections if value)
    hidden = _killer_name(state)
    if hidden:
        joined = joined.replace(hidden, "某个人（姓名保密）")
    return joined


# 卡关提示：用一点提示点换一条“微弱提示”，方向性、不公布答案


def _ask_hint(state: dict[str, Any], stage_guide: str = "") -> str:
    story = state.get("story_details")
    if story is None:
        return "先把案情资料读一遍，再决定先从谁聊起。"

    characters = state.get("characters", [])
    suspects = [
        c for c in characters
        if str(getattr(c, "role", "") or "").strip().lower() != "victim"
    ]
    talked = _talked_names(state)
    untalked = [c for c in suspects if c.name not in talked]
    untalked_names = "、".join(c.name for c in untalked[:3])
    hints_seen = 0
    for raw in state.get("messages", []):
        content = str(raw.get("content") if isinstance(raw, dict) else getattr(raw, "content", "") or "")
        if content.startswith("【提示】"):
            hints_seen += 1

    def _fallback() -> str:
        if not untalked:
            return "把听到的行踪和现场时间对一对：谁的说法对不上，谁就最值得继续追问。"
        if hints_seen == 0:
            return f"先别急着审问，和还没深聊的 {untalked_names} 聊聊当晚的安排，很多线索是聊天里带出来的。"
        return "回看时间线：如果有人说自己一直待在房间，可另一边却有人提到见过他走动，那多半就是突破口。"

    stage_suffix = ("（当前阶段往「" + stage_guide + "」方向再追一步。）") if stage_guide else ""
    if not available():
        return _fallback() + stage_suffix

    prompt = f"""
你是一位克制、口风很紧的侦探助手，正在给悬疑推理游戏里的玩家提供“微弱提示”。

规则：
1. 只给方向性暗示：该追问谁、哪段时间线可能对不上、哪件物品值得再查一次，不要说破最终真相；
2. 不能直接写出真凶姓名，也不能把决定性破绽的关键细节完整复述；
3. 玩家用提示的次数越多，可以稍微具体一点点，但始终是暗示而非公布答案；
4. 控制在 2 句话以内，简体中文，口语化，不要带编号或前缀。

案情（真凶姓名已脱敏）：
{_story_prompt_text(state)}

玩家已经聊过的人：{("、".join(sorted(talked))) if talked else "还没有聊过任何人"}
还没聊过的人：{untalked_names or "全都聊过了"}
这是玩家第 {hints_seen + 1} 次使用提示。
{("建议追问阶段：" + stage_guide) if stage_guide else ""}

只输出这条提示本身。
"""
    try:
        result = raw_invoke([SystemMessage(content=prompt)])
        text = str(result.content).strip()
        return text[:160] if text else _fallback()
    except Exception as exc:  # AI 异常时兜底，不让玩家卡死
        print(f"[提示] LLM 调用失败：{exc}")
        return _fallback()


# 现场调查：玩家主动勘查地点/物品，生成一段“额外隐藏发现”


def _investigate_target(state: dict[str, Any], target: str, extra_reveal: str = "") -> str:
    story = state.get("story_details")
    if story is None:
        return "还没有案情档案，请先开始一局游戏。"

    characters = state.get("characters", [])
    suspect = next(
        (
            c for c in characters
            if c.name
            and str(getattr(c, "role", "") or "").strip().lower() != "victim"
            and c.name in target
        ),
        None,
    )
    relation_brief = f"- 涉及嫌疑人背景：{suspect.backstory}\n" if suspect is not None else ""

    def _fallback() -> str:
        if suspect is not None:
            return f"你推开 {target} 的门，发现表面生活痕迹很少——抽屉底层压着半张被撕掉的照片和一张退掉的船票，日期正好在案发前。你想起{suspect.name}说过自己当晚没出过房间……（离线线索）"
        if "现场" in target:
            return f"你在现场又蹲下身看了一遍：{story.crime_scene_details}。角落一处不起眼的脚印方向与众人进出的路线相反，像是有人绕了远路。（离线线索）"
        if "凶器" in target or story.murder_weapon in target:
            return f"再次检查{story.murder_weapon}：{story.cause_of_death}。握柄处有一道很浅的新擦痕，和被清理过的指纹区不同，像是匆忙间留下的。（离线线索）"
        if "房间" in target:
            return f"你在 {target} 翻到一本夹着书签的日记，书签停在一周前的那一页：写的人似乎在害怕什么人知道某件事。{story.initial_clues or ''}（离线线索）"
        return f"你把与「{target}」相关的记录重新摊开：{story.npc_brief}。翻到背面时，一行被划掉又补上的小字引起了你的注意。（离线线索）"

    if not available():
        return _fallback()

    prompt = f"""
你是悬疑剧本的“现场勘察员”。玩家主动调查了一个对象（地点/物品/房间），请生成一段勘查发现。

要求：
1. 以发现口吻写 2~3 句现场观察，给出能推进调查但尚不能定案的“额外隐藏线索”；
2. 可以呼应{target}特有的细节，让线索和案情自洽；
3. 绝对不要写出“XX是凶手”，也不要直接把决定性破绽完整抖出；暗示即可；
4. 如果这条线索指向某个方向，用含蓄的方式带出来，像侦探压着没说破的发现；
5. 简体中文，不要加标题，不要用“提示：”等前缀。

案情（真凶姓名已脱敏）：
{_story_prompt_text(state)}

{relation_brief}调查对象：{target}

{("- 现场线索中已确认一件可以写进发现的具体事项：\n" + extra_reveal) if extra_reveal else ""}
只输出这段发现本身。
"""
    try:
        result = raw_invoke([SystemMessage(content=prompt)])
        text = str(result.content).strip()
        return text[:400] if text else _fallback()
    except Exception as exc:  # AI 异常时兜底，保证现场调查始终可玩
        print(f"[现场调查] LLM 调用失败：{exc}")
        return _fallback()



__all__ = [
    "_killer_index",
    "_suspect_indexes",
    "_find_skeleton",
    "_build_victim_report",
    "_coach_anchor",
    "_coach_llm_question",
    "_compose_auto_questions",
    "_exposed_reveals_ordered",
    "_reset_chat_progress",
    "_bump_chat_progress",
    "_answer_as_character",
    "_talked_names",
    "_killer_name",
    "_story_prompt_text",
    "_ask_hint",
    "_investigate_target",
]
