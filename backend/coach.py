# coach.py
# “AI 帮我提问”后端规划器：排序未解锁目标 + 生成“自然问法”，供 oracle 预检放行
#
# 职责边界：
#   1) 从“当前对象仍未解锁的揭示项”里挑最贴当前话题的下一个目标（确定性排序）；
#   2) 为每个目标生成候选问法：先试自然闲聊式（时间/地点/物件/人物），
#      兜底是“对一对”核实问——问题本身与目标揭示强重叠，能让 oracle 可靠命中；
#   3) LLM 个性化措辞由 main.py 负责注入（含角色骨架的“可公开人设”，绝不含秘密本体）。

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Sequence

_PUNCT_RE = re.compile(r"[\s，。！？、；：“”\"'‘’（）()\-—–·.…【】《》]+")


def clean_text(raw: str) -> str:
    return _PUNCT_RE.sub("", raw or "").lower()


_STOP_GRAMS = {
    "什么", "怎么", "那个", "这个", "一个", "不是", "你们", "他们", "我们", "自己", "时候", "知道",
    "觉得", "还是", "没有", "然后", "现在", "还有", "真的", "今天", "明天", "因为", "如果", "但是",
    "所以", "而且", "可以", "可能", "应该", "就是", "这样", "那样", "那么", "的话", "到底", "究竟",
}


def _grams(raw: str) -> set[str]:
    text = clean_text(raw)
    grams: set[str] = set()
    for index in range(len(text) - 1):
        grams.add(text[index : index + 2])
    return grams


def text_overlap(a: str, b: str) -> int:
    """粗略的相关度（2-gram 交集），只用于给下一个目标排序。"""
    ga = _grams(a or "")
    gb = _grams(b or "")
    if not ga or not gb:
        return 0
    shared = sum(1 for g in ga if g not in _STOP_GRAMS and g in gb)
    return min(shared, 8)


def clip(raw: str, max_len: int = 22) -> str:
    text = re.sub(r"[“”「」『』\s]+", " ", (raw or "")).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "……"


def leadless(text: str) -> str:
    """剥掉“XX说 / 还提到 / 则坚持说”等前缀，只留后半句。"""
    out = re.sub(
        r"^.{0,12}?(?:还提到|则坚持说|最后说|提到过|说道|讲到|说[，,：:]|讲[，,：:])\s*",
        "", text or "",
    ).strip()
    return out or (text or "")


_TIME_FULL = re.compile(
    r"(?:凌晨|清晨|早上|上午|中午|午后|下午|傍晚|晚上|夜里|半夜|深夜|昨晚|那晚|当晚|前天|大前天|将近|差不多)?"
    r"\s*[0-9〇零一二三四五六七八九十两]{1,4}\s*[:：点]"
    r"[0-9〇零一二三四五六七八九十两多点半整分前后]{1,8}"
)
_PLACE_WORDS = [
    "走廊", "楼梯口", "侧门", "门口", "大厅", "前厅", "客厅", "书房", "书桌前", "卧室", "厨房", "车库",
    "花园", "后院", "院子", "阳台", "露台", "凉亭", "地下室", "楼下", "楼上", "房间", "厢房", "西翼", "东翼",
    "窗边", "窗台", "过道", "楼梯", "里屋", "甲板", "车厢", "包厢", "船舱", "船头", "船尾", "库房", "账房",
]
_OBJECT_WORDS = [
    "遗嘱", "草稿", "账本", "账目", "转账", "信托", "基金", "钥匙", "信封", "纸条", "日记", "照片", "信",
    "药", "杯子", "酒杯", "红酒", "热红酒", "托盘", "瓶子", "船票", "车票", "戒指", "项链", "怀表", "手机",
    "袖扣", "文件", "合同", "欠条", "账单", "礼盒", "剪刀", "复印件", "花瓶", "古董", "遗嘱草稿", "枪",
    "匕首", "烛台", "绳索", "丝巾", "针筒", "锤子", "铁棒", "斧头", "遗物", "遗书", "收据", "发票", "血",
]
_EVENT_WORDS = [
    "吵", "争吵", "争执", "闹翻", "闹", "离婚", "分居", "分手", "债", "欠", "借钱", "催", "瞒", "躲", "威胁",
    "翻脸", "摔", "打翻", "气", "哭", "怕", "不对劲", "打碎", "斥责", "换掉", "辞退", "赶走", "审计", "查账",
    "涂改", "对不上", "说谎", "撒谎", "隐瞒", "心虚", "私会", "吵醒", "发火", "动怒", "圆谎",
]


def _find_any(text: str, words: Sequence[str]) -> str:
    for word in words:
        if word and (text or "").find(word) >= 0:
            return word
    return ""


def find_time(text: str) -> str:
    source = text or ""
    match = _TIME_FULL.search(source)
    if match:
        return match.group(0).strip()
    loose = re.search(r"[0-9〇零一二三四五六七八九十两]{1,4}\s*[:：点]", source)
    if loose:
        return re.sub(r"[：:]$", "点", loose.group(0))
    return ""


def _anchor_of(text: str) -> str:
    time = find_time(text)
    if time:
        return time
    return _find_any(text, [*_PLACE_WORDS, *_OBJECT_WORDS, *_EVENT_WORDS])


def _attr(obj: Any, name: str, default: str = "") -> str:
    if isinstance(obj, dict):
        return str(obj.get(name, default) or default)
    return str(getattr(obj, name, default) or default)


def _clause_around(body: str, anchor_index: int) -> str:
    """取包含锚点的完整分句（以逗号/句号等为界），避免引到半截词。"""
    punct = "，。！？、；；：";
    start = 0
    for cursor in range(anchor_index - 1, -1, -1):
        if body[cursor] in punct:
            start = cursor + 1;
            break
    end = len(body)
    for cursor in range(start, len(body)):
        if body[cursor] in punct:
            end = cursor;
            break
    return body[start:end].strip()


def confirm_question(item_text: str) -> Optional[str]:
    """“对一对”核实问：问题与目标揭示强重叠，能让 oracle 稳定命中。"""
    body = leadless(item_text or "").strip()
    anchor = _anchor_of(body)
    if not anchor:
        return None
    index = body.find(anchor)
    if index < 0:
        return None
    clause = _clause_around(body, index)
    if not clause:
        return None
    clause = re.sub(r"^(她|他|那女人|那人)", "你", clause)
    clause = re.sub(r"(她|他)$", "你", clause)
    clause = re.sub(r"[。！？，、；；：]+$", "", clause)
    clause = clip(clause, 22)
    if len(clean_text(clause)) < 4:
        return None
    return f"对了，有件事我想跟你对一对——“{clause}”，是不是真有这么回事？"


def natural_probes(item_text: str, victim: str) -> List[str]:
    """自然闲聊式问法（不做内容引用，命中率低于确认问，但更像唠嗑）。

    同一类目标（时间/地点/物件）用不同模板轮换措辞，避免每次点击 AI 代问
    都像复读机一样抛出同一句式。
    """
    text = item_text or ""
    out: List[str] = []

    def pick(templates: Sequence[str], key: str) -> str:
        tokens = [ord(ch) for ch in (key or "")]
        index = sum(tokens) % len(templates) if tokens else 0
        return templates[index]

    time = find_time(text)
    if time:
        t = clip(time, 10)
        phrase = pick(
            [
                f"把时间理一理——{t}那会儿你大概在做什么？有人看见过你吗？",
                f"说起来，{t}前后你人在哪儿？那会儿庄园里还有谁没睡？",
                f"{t}那会儿你应该还在庄园里吧——当时在忙什么，有碰见谁吗？",
                f"能不能再帮我想想{t}前后的细节？我总觉得那段时间有哪儿对不上。",
            ],
            t,
        )
        out.append(phrase)
    place = _find_any(text, _PLACE_WORDS)
    if place:
        out.append(f"你说的那个{place}——出事那阵子你常过去吗？都碰见过谁？")
    obj = _find_any(text, _OBJECT_WORDS)
    if obj:
        out.append(f"对了，那个{obj}……我到现在都没想明白，你后来还有没有再见到它？")
    event = _find_any(text, _EVENT_WORDS)
    if event and re.search(r"吵|闹|争执|翻脸|摔|打翻|吼|吵醒", event):
        out.append(f"听你这语气，那事不像一天两天了——那晚到底为啥{event}起来的，能跟我唠唠不？")
    if victim and victim in text:
        out.append(f"你最后一次见{victim}是什么时候？那会儿她瞧着还好吗？")
    return out


def rank_locked(
    locked: Sequence[Any],
    npc_last: str,
    player_last: str,
    case_blob: str,
    persona_blob: str,
) -> List[Any]:
    """按与当前话题 / 公开案情 / 角色档案的相关度，给未解锁目标排序。"""
    scored = []
    for index, item in enumerate(locked):
        text = _attr(item, "text")
        score = 0.0
        score += text_overlap(text, npc_last) * 2.2
        score += text_overlap(text, player_last) * 1.5
        score += text_overlap(text, case_blob) * 0.9
        score += text_overlap(text, persona_blob) * 1.2
        scored.append((score, index, item))
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [entry[2] for entry in scored]


def candidate_questions(
    character: Any,
    story: Any,
    npc_last: str,
    player_last: str,
    locked: Sequence[Any],
    llm_questions: Sequence[str],
    avoid: Sequence[str] = (),
) -> List[str]:
    """组装“最终候选问法”列表：LLM 措辞优先，自然问法其次，确认问兜底。

    avoid：本段对话里玩家已经问过的话（clean 后），不再重复生成，避免每次点
    “AI 帮我提问”都抛出同一句。
    """
    out: List[str] = []
    seen: set[str] = set()
    avoid_keys = {clean_text(q) for q in (avoid or ()) if q and clean_text(q)}

    def add(raw: Optional[str]):
        text = (raw or "").strip()
        key = clean_text(text)
        if text and key and key not in seen and key not in avoid_keys:
            seen.add(key)
            out.append(text)

    for question in llm_questions:
        add(question)

    victim = _attr(story, "victim_name")
    case_blob = "\n".join([
        _attr(story, "crime_scene_details"),
        _attr(story, "initial_clues"),
        _attr(story, "npc_brief"),
        _attr(story, "time_of_death"),
        _attr(story, "location_found"),
    ])
    persona_blob = "\n".join([_attr(character, "backstory"), _attr(character, "relation_to_victim")])
    ordered = rank_locked(locked, npc_last, player_last, case_blob, persona_blob) if locked else []

    if not locked:
        # 对方能挖的都挖完了：只给“接着刚才的话”的闲聊，不再硬编审问句
        generic = []
        frag = _conversation_fragment(npc_last)
        if frag:
            generic.append(f"你刚说“{frag}”——咱们把话倒回那晚，那阵子你都做了什么、见过谁，慢慢跟我说说？")
        generic.append("你先歇口气——我这边想问的基本问完了。今晚的事，你还有什么想主动跟我说的吗？")
        for q in generic:
            add(q)
        return out

    # 自然问法（对前 2 个最贴话题的目标）
    for item in ordered[:2]:
        for question in natural_probes(_attr(item, "text"), victim):
            add(question)

    # 确认问兜底（对前 3 个目标，保证至少有一条能可靠命中 oracle）
    for item in ordered[:3]:
        add(confirm_question(_attr(item, "text")))
    return out


def _conversation_fragment(npc_last: str, max_len: int = 14) -> str:
    source = (npc_last or "").strip()
    if not source:
        return ""
    parts = [p.strip() for p in re.split(r"[，。！？；、\n]", source) if p.strip()]
    for part in parts:
        text = leadless(part).strip()
        if len(text) < 4 or len(text) > max_len:
            continue
        if re.match(r"^(其实|就是|不过|但是|然后|反正|对了|唉|嗯|呃|啊|哦|那个|这个|主要|因为|所以)", text):
            continue
        if text.endswith(("吗", "呢")):
            continue
        return text
    cleaned = leadless(source)
    if len(cleaned) >= 4:
        return cleaned[:max_len]
    return ""


__all__ = [
    "clean_text",
    "text_overlap",
    "leadless",
    "find_time",
    "clip",
    "confirm_question",
    "natural_probes",
    "rank_locked",
    "candidate_questions",
    "_conversation_fragment",
]
