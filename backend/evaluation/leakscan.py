# evaluation/leakscan.py
# 评估侧的“真相泄露”字面扫描：两处用途
#   1. 回合级：检查 NPC 回复里有没有出现尚未放行的揭示原文，或直接复述作案过程；
#   2. 落盘前：报告 / 样本文件写盘之前统一扫一遍，命中就脱敏并计数（绝不静默放过）。
#
# 为什么复用 role_skeleton.guard 的原语：
#   线上是 LeakGuard 在拦输出，评估如果自己另写一套口径，两边会打架——同一句话
#   线上判干净、评估判泄露就没人信了。这里直接复用 normalize / _anchors /
#   _longest_common_run_len，长公共子串这一判据和线上完全一致。

from __future__ import annotations

from typing import Any, Iterable, List, Sequence, Tuple

from role_skeleton.guard import _anchors, _longest_common_run_len, normalize

# 判定“这是同一段话”的最短连续公共子串长度（字符数，已去标点）。
# 12 与 guard 内部的秘密 / 未知事实锚点阈值同量级：短于此的偶然撞词不算泄露。
ANCHOR_MIN_LEN = 12

# 脱敏后替换成的占位文本，报告里一眼能看出被拦过。
REDACTED = "[redacted]"


def text_anchors(texts: Iterable[str], min_len: int = ANCHOR_MIN_LEN) -> List[str]:
    """把若干段文本切成可用于比对的长锚点（规范化后）。"""
    return _anchors([str(t) for t in texts if str(t or "").strip()], min_len)


def truth_anchors(story: Any, skeletons: Iterable[Any] = ()) -> List[str]:
    """内部真相锚点：作案过程 + 每副骨架的 secrets / private_facts。

    这些内容是硬约束里只能待在服务端的部分，任何对外产物都不得出现。
    """
    texts: List[str] = []
    process = ""
    if isinstance(story, dict):
        process = story.get("murder_process") or ""
    elif story is not None:
        process = getattr(story, "murder_process", "") or ""
    if process:
        texts.append(str(process))
    for skeleton in skeletons or ():
        for secret in getattr(skeleton, "secrets", ()) or ():
            content = getattr(secret, "content", "")
            if content:
                texts.append(str(content))
        for fact in getattr(skeleton, "private_facts", ()) or ():
            if fact:
                texts.append(str(fact))
    return text_anchors(texts)


def anchors_hit(text: str, anchors: Sequence[str], min_run: int = ANCHOR_MIN_LEN) -> List[str]:
    """返回命中的锚点（截断后便于日志查看，不含完整原文）。"""
    norm = normalize(text or "")
    if not norm:
        return []
    hits: List[str] = []
    for anchor in anchors:
        if _longest_common_run_len(norm, anchor) >= min_run:
            hits.append(anchor[:24])
    return hits


def scan_and_redact(
    payload: Any,
    anchors: Sequence[str],
    *,
    min_run: int = ANCHOR_MIN_LEN,
    placeholder: str = REDACTED,
) -> Tuple[Any, int]:
    """深度遍历 payload，命中真相锚点的字符串整体替换为占位符。

    返回 (脱敏后的新对象, 脱敏次数)。这里不抛异常——报告依然要写出来，但次数会被
    记进报告，让“这次拦掉了什么级别的泄露”看得见。
    """
    if not anchors:
        return payload, 0
    counter = {"n": 0}

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            if node and anchors_hit(node, anchors, min_run):
                counter["n"] += 1
                return placeholder
            return node
        if isinstance(node, dict):
            return {key: _walk(value) for key, value in node.items()}
        if isinstance(node, (list, tuple)):
            walked = [_walk(item) for item in node]
            return type(node)(walked) if isinstance(node, tuple) else walked
        return node

    cleaned = _walk(payload)
    return cleaned, counter["n"]


__all__ = [
    "ANCHOR_MIN_LEN",
    "REDACTED",
    "anchors_hit",
    "scan_and_redact",
    "text_anchors",
    "truth_anchors",
]
