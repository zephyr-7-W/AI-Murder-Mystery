# judge.py
# 结算 / 推理质量评判（后端）
#
# 与前端 utils/scoring.ts 的“本地确定性打分”互补：
#   1) 线索收集完整度：基于服务端真相 oracle 已放行比例（权威口径，不依赖前端猜测）；
#   2) 推理理由得分：优先让 LLM 把玩家理由与真相链逐条比对（抓到哪些矛盾、漏了哪些），
#      离线 / 模型异常时退回与前端一致的确定性关键词规则；
#   3) 指认正确 + 剩余次数给加分。
#
# 纯函数部分（score_game / reason_heuristic）不依赖大模型，可直接注入 fake LLM 单测。

from __future__ import annotations

import json
import re
from typing import Any, Callable, Iterable, List, Optional


_TRUTH_TERMS_RE = re.compile(
    r"乌头碱|毒|红酒|杯|袖扣|遗嘱|涂改|受益人|信托|账目|转账|审计|海外转账|"
    r"钥匙|烟蒂|露台|花园侧门|走廊|争吵|十点四|九点五|潜入|擦掉|换回"
)


def _norm(text: str) -> str:
    cleaned = re.sub(r"[\s，。！？、：；“”’‘（）()\-—–·.…【】《》]", "", text or "").lower()
    return cleaned.replace(chr(34), "").replace(chr(39), "")


def grade_label(score: int) -> str:
    if score >= 90:
        return "S · 名侦探"
    if score >= 75:
        return "A · 老练刑警"
    if score >= 60:
        return "B · 合格探员"
    if score >= 40:
        return "C · 线索半解的见习生"
    return "D · 被凶手带偏的旁观者"


def _attr(obj: Any, name: str, default: str = "") -> str:
    if isinstance(obj, dict):
        return str(obj.get(name, default) or default)
    return str(getattr(obj, name, default) or default)


def _terms_of(story: Any) -> List[str]:
    terms: List[str] = []
    if story is not None:
        for key in ("victim_name", "murder_weapon", "location_found"):
            value = _attr(story, key).strip()
            if len(value) >= 2:
                terms.append(value)
        match = re.search(r"\d{1,2}\s*[:：点]\d{0,2}", _attr(story, "time_of_death"))
        if match:
            terms.append(match.group(0))
        for part in _TRUTH_TERMS_RE.findall(_attr(story, "murder_process")):
            if part and len(part) >= 2:
                terms.append(part)
    seen = set()
    result: List[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            result.append(term)
    return result


def reason_heuristic(reason: str, story: Any, killer_name: str) -> int:
    reason = (reason or "").strip()
    norm_reason = _norm(reason)
    if not reason:
        return 0
    terms = _terms_of(story)
    if killer_name and len(killer_name) >= 2:
        terms.append(killer_name)
    hit = 0
    for term in terms:
        clean = _norm(term)
        if clean and len(clean) >= 2 and clean in norm_reason:
            hit += 1
    length_score = (
        40 if len(reason) >= 60 else
        30 if len(reason) >= 30 else
        20 if len(reason) >= 12 else
        8
    )
    if not terms:
        return length_score
    term_score = min(60, round((hit / min(len(terms), 10)) * 60))
    return min(100, length_score + term_score)


def _parse_llm_reasoning(text: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        block = re.search(r"\{[\s\S]*?\}", text)
        if block:
            payload = json.loads(block.group(0))
            if isinstance(payload, dict):
                return payload
    except Exception:
        pass
    score = None
    match = re.search(r"(?:reasoning|score|分数|推理得分)\D{0,6}(\d{1,3})", text)
    if match:
        try:
            score = int(match.group(1))
        except ValueError:
            score = None
    found = re.findall(r"(?:抓到|命中|关键|found)[^\n。]{0,40}", text)
    missed = re.findall(r"(?:漏掉|遗漏|missed|未覆盖)[^\n。]{0,40}", text)
    return {
        "score": score,
        "key_points_found": found[:4],
        "key_points_missed": missed[:4],
        "feedback": (text or "")[:200],
    }


def reason_with_llm(
    reason: str,
    story: Any,
    killer_name: str,
    llm_fn: Optional[Callable[[str], str]] = None,
) -> dict[str, Any]:
    """LLM judge：把玩家推理理由与真相链逐条比对。

    llm_fn 接收完整提示词文本并返回文本，单测可传 fake。
    """
    if llm_fn is None:
        return {}
    lines: List[str] = []
    lines.append("你是推理游戏的结案评审。玩家的指认理由与真相如下，请逐条比对：")
    lines.append("1) 玩家是否抓到关键矛盾/决定性证据；")
    lines.append("2) 漏掉了哪些能锁定凶手的细节；")
    lines.append("3) 给推理质量打 0-100 分。")
    lines.append("")
    lines.append("真相（仅评审可见）：")
    for key in (
        "victim_name", "time_of_death", "location_found", "murder_weapon",
        "cause_of_death", "crime_scene_details", "witnesses", "npc_brief",
        "murder_process",
    ):
        value = _attr(story, key)
        if value:
            lines.append("- " + key + "：" + value)
    lines.append("真凶：" + killer_name)
    lines.append("")
    lines.append("玩家推理理由：")
    lines.append(reason or "（未填写）")
    lines.append("")
    lines.append(chr(123) + chr(34) + "score" + chr(34) + ":0-100," + chr(34) + "key_points_found" + chr(34) + ":[..]," + chr(34) + "key_points_missed" + chr(34) + ":[..]," + chr(34) + "feedback" + chr(34) + ":" + chr(34) + "一句总评" + chr(34) + chr(125))
    prompt = "\n".join(lines)
    try:
        text = llm_fn(prompt) or ""
    except Exception as exc:
        print(f"[结算评审] LLM judge 调用失败：{exc}")
        return {}
    return _parse_llm_reasoning(text)


def score_game(
    oracle_items: Iterable[Any],
    *,
    reason: str = "",
    guess_correct: bool = False,
    guesses_left: int = 0,
    max_guesses: int = 3,
    llm_fn: Optional[Callable[[str], str]] = None,
    story: Any = None,
    killer_name: str = "",
) -> dict[str, Any]:
    items = list(oracle_items or [])
    exposed = [item for item in items if getattr(item, "exposed", False)]
    total = max(len(items), 1)
    clue_coverage = min(100, round((len(exposed) / total) * 100))
    parsed = reason_with_llm(reason, story, killer_name, llm_fn=llm_fn) if llm_fn is not None else {}
    raw_score = parsed.get("score")
    if raw_score is not None:
        try:
            reasoning = int(raw_score)
        except (TypeError, ValueError):
            reasoning = reason_heuristic(reason, story, killer_name)
    else:
        reasoning = reason_heuristic(reason, story, killer_name)
    reasoning = max(0, min(100, reasoning))
    bonus = (15 if guess_correct else 0) + max(0, int(guesses_left)) * 3
    total_score = max(0, min(100, round(clue_coverage * 0.35 + reasoning * 0.5 + bonus)))
    key_found: List[str] = []
    key_missed: List[str] = []
    for item in sorted(items, key=lambda it: (int(getattr(it, "stage", 0) or 0), str(getattr(it, "id", "")))):
        text = str(getattr(item, "text", "") or "")
        stage = int(getattr(item, "stage", 0) or 0)
        if getattr(item, "exposed", False) and stage >= 1:
            key_found.append(text)
        elif not getattr(item, "exposed", False) and stage >= 2:
            key_missed.append(text)
    found_extras = [str(x) for x in (parsed.get("key_points_found") or [])][:3]
    missed_extras = [str(x) for x in (parsed.get("key_points_missed") or [])][:3]
    key_found = (key_found + found_extras)[:4]
    key_missed = (key_missed + missed_extras)[:4]
    return {
        "total": total_score,
        "clueCoverage": clue_coverage,
        "reasoning": reasoning,
        "bonus": bonus,
        "grade": grade_label(total_score),
        "keyPointsFound": key_found,
        "keyPointsMissed": key_missed,
        "feedback": str(parsed.get("feedback") or "")[:120],
    }


__all__ = ["score_game", "reason_heuristic", "grade_label", "reason_with_llm", "_parse_llm_reasoning"]