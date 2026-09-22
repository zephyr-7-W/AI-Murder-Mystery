# oracle.py
# 真相 oracle + 结构化揭示
#
# 把“线索只在问对问题时解锁”从‘前端近似匹配 + 提示词约束’升级成服务端机制：
#   1. build_oracle_items()：开局时从案情文本确定性提取每个嫌疑人“可被问出的揭示项”；
#   2. oracle_choose()：只有玩家问题真正命中某条未揭示项（主题/专名/字面重叠打分）才放行；
#   3. 放行后的揭示文本才允许进入扮演该 NPC 的大模型上下文（_answer_as_character），
#      未被放行的揭示内容对扮演模型不可见 -> 角色无法在闲聊时“倒豆子”；
#   4. 揭示项随会话持久化，服务重启后已解锁状态不丢。
#
# 关键边界：
#   - 真凶姓名、murder_process 永远不进入 oracle 文本（它们只存在于内部 state 与凶手骨架）。
#   - 揭示项文本与前端 src/utils/clueUtils.ts 的抽取规则保持一致，保证“服务端放行”
#     能点亮“前端那条锁定线索”。

from __future__ import annotations

import re
import time
from typing import Any, Iterable, List, Optional

from pydantic import BaseModel, Field


class OracleItem(BaseModel):
    """一条“可被问出的结构化揭示”。"""

    id: str = Field(description="唯一标识")
    owner: str = Field(description="归属嫌疑人姓名")
    text: str = Field(description="揭示文本（来自案情卷宗，不含真凶结论）")
    exposed: bool = Field(default=False, description="是否已向玩家放行")
    exposed_at: float = Field(default=0.0, description="放行时间戳（毫秒）")
    stage: int = Field(default=0, description="揭示阶段：0 行踪 / 1 矛盾 / 2 决定性（旧数据默认 0，不阻塞放行）")


STAGE_LABELS: dict[int, str] = {
    0: "行踪与当晚安排",
    1: "矛盾细节",
    2: "决定性细节",
}


def stage_label(stage: int) -> str:
    """阶段名：行踪 → 矛盾 → 决定性。"""
    return STAGE_LABELS.get(int(stage or 0), STAGE_LABELS[0])


def stage_of_index(index: int) -> int:
    """每个角色揭示项的推进深度（0-2）。按项序两两一档，防止一上来就挖到决定性细节。"""
    return min(2, max(0, int(index or 0) // 2))


def revealable_items(items: Iterable[OracleItem]) -> List[OracleItem]:
    """只返回‘当前阶段允许放行’的未揭示项。

    门控规则：同一归属人里，比该项更浅的阶段必须全部已放行，深一档才解锁。
    旧存档若没有 stage 字段（默认 0），等价于所有项同一档，不限制放行。
    """
    if not items:
        return []
    by_owner: dict[str, List[OracleItem]] = {}
    for item in items:
        by_owner.setdefault(item.owner, []).append(item)
    result: List[OracleItem] = []
    for owner_items in by_owner.values():
        for item in owner_items:
            if item.exposed:
                continue
            shallower = [other for other in owner_items if other.stage < item.stage]
            if all(other.exposed for other in shallower):
                result.append(item)
    return result


def next_stage_guide(owner_items: Iterable[OracleItem]) -> dict[str, Any]:
    """给 AI 代问/提示系统用的阶段引导信息（不泄露文本，只说方向）。"""
    items = list(owner_items or [])
    if not items:
        return {"owner": "", "label": "", "unlocked": 0, "total": 0}
    owner = items[0].owner
    total = len(items)
    unlocked = sum(1 for item in items if item.exposed)
    revealable = revealable_items(items)
    if not revealable:
        return {"owner": owner, "label": "", "unlocked": unlocked, "total": total}
    next_item = min(revealable, key=lambda item: (item.stage, item.id))
    return {
        "owner": owner,
        "label": stage_label(next_item.stage),
        "stage": int(next_item.stage),
        "unlocked": unlocked,
        "total": total,
    }


def proximity_signal(
    question: str,
    revealable: Iterable[OracleItem],
    story: Any,
    characters: Iterable[Any],
) -> tuple[int, Optional[OracleItem]]:
    """‘差一点命中’的软反馈信号。

    当问题实质在聊案情、又没达到 oracle_choose 的放行分时，返回 1（低）/ 2（中）。
    这条信号不进 reveal_log、不写证词记录，只用于让 NPC/系统给一句“方向对了，再具体点”。
    """
    if not question_is_substantive(question or "", story, characters):
        return 0, None
    candidates = list(revealable or [])
    best: Optional[OracleItem] = None
    best_score = 0
    for item in candidates:
        score = relevance_score(question or "", str(item.text or ""), story, characters)
        if score > best_score:
            best_score = score
            best = item
    if best is None or best_score <= 0:
        return 0, None
    # 2 分正好是 oracle_choose 的放行线：能到 2 就不该出现在这里，保守只给 1。
    return (2 if best_score >= 3 else 1), best


# ---------- 与前端 clueUtils.ts / questionGate.ts 保持一致的确定性逻辑 ----------

_NORM_PUNCT = set("，。！？、：；“”（）()—–·.…")
_QUESTION_PUNCT = set("，。！？、；：；“”（）()—–·.…【】《》")
_WHITESPACE = None


def _norm(text: str) -> str:
    out: list[str] = []
    for ch in str(text or "").lower():
        if ch in _NORM_PUNCT or ch.isspace():
            continue
        out.append(ch)
    return "".join(out)


def _clean_q(text: str) -> str:
    out: list[str] = []
    for ch in str(text or "").lower():
        if ch in _QUESTION_PUNCT or ch.isspace():
            continue
        out.append(ch)
    return "".join(out)


def split_clue_text(text: str) -> List[str]:
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"[\n\r]+|、|；|;", text) if p and p.strip()]
    if 1 < len(parts) <= 20:
        return parts
    by_punct = [p.strip() for p in re.split(r"[。！？!?]", text) if p and p.strip()]
    if 1 < len(by_punct) <= 20:
        return by_punct
    return [text.strip()] if text and text.strip() else []


def _sentences_from(text: str) -> List[str]:
    if not text:
        return []
    return [
        s.strip()
        for s in re.split(r"[\n\r]+|[。！？!?；;]+", text)
        if s and len(s.strip()) >= 6
    ]


def _attr(obj: Any, name: str, default: str = "") -> str:
    if isinstance(obj, dict):
        return str(obj.get(name, default) or default)
    return str(getattr(obj, name, default) or default)


def build_oracle_items(story: Any, characters: Iterable[Any]) -> List[OracleItem]:
    """与前端 buildClues() 的“调查解锁线索”抽取完全一致，产物是服务端揭示表。"""
    suspects = [
        c for c in characters
        if str(getattr(c, "role", "") or "").strip().lower() != "victim"
    ]
    used_norm = set()

    # 公开线索先占用去重表（与前端一致）
    initial = _attr(story, "initial_clues")
    for raw in split_clue_text(initial)[:14]:
        used_norm.add(_norm(raw))

    scene = _attr(story, "crime_scene_details")
    witnesses = _attr(story, "witnesses")
    npc_brief = _attr(story, "npc_brief")
    pool = _sentences_from("\n".join([scene, witnesses, npc_brief]))
    pickable = [s for s in pool if _norm(s) not in used_norm]

    items: List[OracleItem] = []
    for suspect in suspects:
        name = _attr(suspect, "name")
        hits: List[str] = []
        for sentence in pickable:
            if len(hits) >= 6:
                break
            key = _norm(sentence)
            if name and name in sentence and key not in used_norm:
                hits.append(sentence)
                used_norm.add(key)
        fallback: List[str] = []
        for sentence in pickable:
            if len(fallback) >= 6 - len(hits):
                break
            key = _norm(sentence)
            if key not in used_norm:
                fallback.append(sentence)
                used_norm.add(key)
        for index, text in enumerate((hits + fallback)[:6]):
            items.append(
                OracleItem(
                    id=f"oracle:{name}:{index}",
                    owner=name,
                    text=text,
                    stage=stage_of_index(index),
                )
            )
    return items


# ---------- 与前端 questionGate.ts 一致的打分规则 ----------

TOPIC_RULES: List[tuple[str, str]] = [
    ("time", r"几[点时]|\d{1,2}\s*[:：点]|时间|时分|凌晨|清晨|早上|上午|中午|午后|下午|傍晚|晚上|夜里|半夜|深夜|当晚|那晚|昨晚|前天|几点|点半|钟|整晚|一晚上"),
    ("whereabouts", r"在哪|在哪里|去哪|去哪儿|出门|离开|回来|回房|待在|房间|走廊|门口|大厅|客厅|书房|厨房|卧室|车库|花园|院子|阳台|地下室|现场|楼下|楼上|甲板|车厢|包厢|里屋|后院|别处"),
    ("weapon", r"凶器|烛台|刀|匕首|手枪|枪|绳索|丝巾|毒|药|针筒|注射|杯子|玻璃|锤子|扳手|铁棒|斧头|血|指纹|脚印|毛发|伤口|利刃|钝器"),
    ("object", r"抽屉|柜子|书桌|桌子|床底|衣橱|皮箱|箱子|信封|纸条|日记|照片|钥匙|怀表|手机|戒指|项链|遗物|信|遗书|账本|船票|车票|票据|收据|发票"),
    ("death", r"死|尸体|遇害|身亡|被杀|出事|案发|命案|害死|被害|血迹|致命伤|死因"),
    ("relation", r"关系|认识|熟悉|朋友|同事|上司|下属|恋人|情侣|夫妻|兄妹|姐弟|父母|兄弟|对手|仇人|情敌|债|欠|借钱|遗嘱|继承|家产|钱|房产|股份|合同|威胁|勒索|敲诈|秘密|隐瞒|说谎|撒谎|骗|动机|为什么|为何|恨|讨厌|嫉妒|过节|矛盾"),
    ("witness", r"看见|看到|听到|听见|发现|目击|路过|经过|注意到|遇到|撞见|听见|证词|说法"),
]

STOP_BIGRAMS = {
    "什么", "怎么", "那个", "这个", "一个", "不是", "你们", "他们", "我们",
    "自己", "时候", "知道", "觉得", "还是", "没有", "然后", "现在", "还有",
    "真的", "今天", "明天", "因为", "如果", "但是", "所以", "而且", "可以",
    "可能", "应该", "就是", "这样", "那样", "那么", "的话", "到底", "究竟",
}

_COMPILED_TOPICS = [(key, re.compile(pattern)) for key, pattern in TOPIC_RULES]


def _topics_of(raw: str) -> set[str]:
    text = _clean_q(raw)
    found = set()
    for key, pattern in _COMPILED_TOPICS:
        if pattern.search(text):
            found.add(key)
    return found


def _bigrams_of(raw: str) -> set[str]:
    text = _clean_q(raw)
    grams: set[str] = set()
    for index in range(len(text) - 1):
        grams.add(text[index : index + 2])
    return grams


def _entity_hits(raw: str, story: Any, characters: Iterable[Any]) -> set[str]:
    text = _clean_q(raw)
    hits: set[str] = set()
    terms = [
        _attr(story, "victim_name"),
        _attr(story, "murder_weapon"),
        _attr(story, "location_found"),
    ]
    terms += [_attr(c, "name") for c in characters]
    for term in terms:
        clean = _clean_q(term)
        if len(clean) >= 2 and clean and clean in text:
            hits.add(clean)
    return hits


def oracle_choose(
    question: str,
    items: Iterable[OracleItem],
    story: Any,
    characters: Iterable[Any],
) -> Optional[OracleItem]:
    """在‘尚未放行’的揭示项里挑与问题最相关的一条；得分不足视为闲聊，返回 None。"""
    q_text = (question or "").strip()
    candidates = [item for item in items if not item.exposed]
    if not q_text or not candidates:
        return None

    q_topics = _topics_of(q_text)
    q_entities = _entity_hits(q_text, story, characters)
    q_bigrams = _bigrams_of(q_text)

    best: Optional[OracleItem] = None
    best_score = 0
    for item in candidates:
        clue_text = (item.text or "").strip()
        if not clue_text:
            continue
        c_topics = _topics_of(clue_text)
        c_entities = _entity_hits(clue_text, story, characters)

        topic_intersect = sum(1 for topic in q_topics if topic in c_topics)
        entity_intersect = sum(1 for entity in q_entities if entity in c_entities)

        shared = 0
        c_bigrams = _bigrams_of(clue_text)
        for gram in q_bigrams:
            if gram in c_bigrams and gram not in STOP_BIGRAMS:
                shared += 1

        score = topic_intersect * 2 + entity_intersect * 3 + min(shared, 3)
        if score > best_score:
            best_score = score
            best = item

    if best is not None and best_score >= 2:
        return best
    return None


def question_is_substantive(question: str, story: Any, characters: Iterable[Any]) -> bool:
    """一句“真在问案情”的话：含时间/地点/人物/物品/关系/目击等信号，才算实质推进。

    纯寒暄（hi / 今天天气不错）没有任何话题或实体信号，不会累积进度，也不会解锁。
    """
    text = (question or "").strip()
    if not text:
        return False
    return bool(_topics_of(text) or _entity_hits(text, story, characters))


def _signals(raw: str, story: Any, characters: Iterable[Any]) -> dict:
    return {
        "topics": _topics_of(raw),
        "entities": _entity_hits(raw, story, characters),
        "bigrams": _bigrams_of(raw),
    }


def touches_reveal(question: str, item_text: str, story: Any, characters: Iterable[Any]) -> bool:
    """这句话与某条揭示是否“沾边”（弱于单句命中，供多轮累计使用）。

    单句命中 oracle_choose 已经要 topics/entities/2+bigram 才算分；这里更宽——
    共享任意 1 个有效 bigram 也算沾边，连续两轮沾到同一条就放行。
    """
    q = _signals(question or "", story, characters)
    c = _signals(item_text or "", story, characters)
    if q["topics"] & c["topics"]:
        return True
    if q["entities"] & c["entities"]:
        return True
    shared = sum(1 for gram in q["bigrams"] if gram in c["bigrams"] and gram not in STOP_BIGRAMS)
    return shared >= 1


def relevance_score(question: str, item_text: str, story: Any, characters: Iterable[Any]) -> int:
    """“沾边”程度打分，用于多轮兜底时挑最近话题的一条。"""
    q = _signals(question or "", story, characters)
    c = _signals(item_text or "", story, characters)
    topic_intersect = len(q["topics"] & c["topics"])
    entity_intersect = len(q["entities"] & c["entities"])
    shared = sum(1 for gram in q["bigrams"] if gram in c["bigrams"] and gram not in STOP_BIGRAMS)
    return topic_intersect * 2 + entity_intersect * 3 + min(shared, 3)


def expose_item(item: OracleItem) -> None:
    if not item.exposed:
        item.exposed = True
        item.exposed_at = time.time() * 1000.0


__all__ = [
    "OracleItem",
    "build_oracle_items",
    "oracle_choose",
    "expose_item",
    "question_is_substantive",
    "touches_reveal",
    "relevance_score",
    "stage_label",
    "stage_of_index",
    "revealable_items",
    "next_stage_guide",
    "proximity_signal",
]
