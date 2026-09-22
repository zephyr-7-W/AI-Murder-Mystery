# guard.py
# 角色骨架层 —— 输出防泄露 / 防出戏检测器
#
# 职责：对“动态对话层”刚生成的文本做确定性检查，不依赖另一个大模型打分：
#   1) 字面禁止短语（forbidden_phrases）
#   2) 正则禁止模式（forbidden_patterns，例如数字底价）
#   3) 出戏话术（meta_leak_patterns + 内置默认，例如“作为AI……”）
#   4) 自己绝密内容的复述检测（secret 锚点：连续长匹配）
#   5) 知识边界检测（knowledge.unknown 锚点：本该不知道的事实被说出）
#
# 锚点文本只保存在检测器里，绝不进入 prompt，避免把秘密“教”给模型。

from __future__ import annotations

import re
import unicodedata
from typing import List

from pydantic import BaseModel, Field

from .schema import RoleSkeleton


DEFAULT_META_PATTERNS: List[str] = [
    r"作为\s*(?:一个\s*)?(?:AI|人工智能|大模型|大语言模型|语言模型|智能助手)",
    r"我(?:是|算)(?:一个\s*)?(?:AI|人工智能|大模型|大语言模型|语言模型|智能助手)",
    r"(?:系统提示|系统设定|角色设定|提示词|人设文件|剧本要求)",
    r"我(?:不能|无法)继续(?:扮演|模拟)",
]


def normalize(text: str) -> str:
    """去掉空白与标点、转小写，保留中文/字母/数字，用于字面比对。"""
    keep = []
    for ch in str(text).lower():
        if unicodedata.category(ch) in {"Ll", "Lu", "Lm", "Lo", "Nd"}:
            keep.append(ch)
    return "".join(keep)


def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"[。！？!?；;\n]+", text or "") if s.strip()]


def _longest_common_run_len(a: str, b: str) -> int:
    """返回两个规范化字符串的最长公共连续子串长度。"""
    if not a or not b:
        return 0
    n = len(b)
    prev = [0] * n
    best = 0
    for ch_a in a:
        cur = [0] * n
        for j, ch_b in enumerate(b):
            if ch_a == ch_b:
                cur[j] = (prev[j - 1] if j else 0) + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _anchors(texts: List[str], min_len: int) -> List[str]:
    """把文本切成句子并规范化，得到只用于匹配的锚点；过短的句子丢弃以免误伤。"""
    anchors: List[str] = []
    seen = set()
    for text in texts:
        for sentence in split_sentences(text):
            norm = normalize(sentence)
            if len(norm) >= min_len and norm not in seen:
                seen.add(norm)
                anchors.append(norm)
    return anchors


class LeakFinding(BaseModel):
    """一次输出审查发现。"""

    source: str = Field(description="发现来源：forbidden_phrase / forbidden_pattern / meta_leak / secret / unknown_fact")
    severity: str = Field(description="hard=确定违规；warning=疑似违规")
    detail: str = Field(description="人类可读的说明")
    matched: str = Field(default="", description="规范化后的命中片段（截断）")


class GuardAudit(BaseModel):
    """一次输出审查结果。"""

    clean: bool
    findings: List[LeakFinding] = Field(default_factory=list)

    @property
    def sources(self) -> List[str]:
        return sorted({f.source for f in self.findings})


class LeakGuard:
    """围绕一副骨架构造的确定性输出检测器。"""

    def __init__(self, skeleton: RoleSkeleton) -> None:
        self.skeleton = skeleton
        policy = skeleton.policy

        self._forbidden_phrases = [
            normalize(p) for p in policy.forbidden_phrases if normalize(p)
        ]
        self._forbidden_patterns = [
            re.compile(p) for p in policy.forbidden_patterns if p
        ]
        meta_sources = list(policy.meta_leak_patterns) + DEFAULT_META_PATTERNS
        self._meta_patterns = [
            re.compile(p) for p in dict.fromkeys(meta_sources) if p
        ]

        # 只用于检测的语料：本角色“不该知道”的事实 + 本角色“绝密”内容锚点。
        self._unknown_anchors = _anchors(skeleton.knowledge.unknown, min_len=6)
        secret_texts: List[str] = []
        for secret in skeleton.secrets:
            secret_texts.append(secret.title)
            secret_texts.append(secret.content)
        self._secret_anchors = _anchors(secret_texts, min_len=10)

    # ---------- 审计 ----------

    def audit(self, text: str) -> GuardAudit:
        findings: List[LeakFinding] = []
        norm_text = normalize(text)

        for phrase in self._forbidden_phrases:
            if phrase and phrase in norm_text:
                findings.append(
                    LeakFinding(
                        source="forbidden_phrase",
                        severity="hard",
                        detail="输出命中禁止输出清单中的字面短语",
                        matched=phrase[:40],
                    )
                )

        for pattern in self._forbidden_patterns:
            match = pattern.search(text or "")
            if match:
                findings.append(
                    LeakFinding(
                        source="forbidden_pattern",
                        severity="hard",
                        detail=f"输出命中禁止输出正则：{pattern.pattern[:40]}",
                        matched=normalize(match.group(0))[:40],
                    )
                )

        for pattern in self._meta_patterns:
            match = pattern.search(text or "")
            if match:
                findings.append(
                    LeakFinding(
                        source="meta_leak",
                        severity="hard",
                        detail="输出出现了跳出角色的元信息（AI/系统设定等）",
                        matched=normalize(match.group(0))[:40],
                    )
                )

        for anchor in self._unknown_anchors:
            self._check_anchor(anchor, norm_text, findings, source="unknown_fact",
                               hard_run=12, warning_run=8)

        for anchor in self._secret_anchors:
            self._check_anchor(anchor, norm_text, findings, source="secret",
                               hard_run=12, warning_run=8)

        return GuardAudit(clean=not findings, findings=findings)

    @staticmethod
    def _check_anchor(anchor: str, norm_text: str, findings: List[LeakFinding],
                      source: str, hard_run: int, warning_run: int) -> None:
        if anchor in norm_text:
            findings.append(
                LeakFinding(
                    source=source,
                    severity="hard",
                    detail="输出了完整的一句话，内容超出允许范围",
                    matched=anchor[:40],
                )
            )
            return
        run = _longest_common_run_len(anchor, norm_text)
        if run >= hard_run:
            findings.append(
                LeakFinding(
                    source=source,
                    severity="hard",
                    detail=f"输出与受限内容存在较长连续重合（{run} 字）",
                    matched=anchor[:40],
                )
            )
        elif run >= warning_run:
            findings.append(
                LeakFinding(
                    source=source,
                    severity="warning",
                    detail=f"输出疑似影射受限内容（连续重合 {run} 字）",
                    matched=anchor[:40],
                )
            )

    # ---------- 修正引导 ----------

    def build_steering(self, findings: List[LeakFinding]) -> str:
        """根据发现类别生成修正指引。刻意不把受限原文放进指引，避免二次污染。"""

        sources = {f.source for f in findings}
        lines = [
            f"{self.skeleton.display_name}（{self.skeleton.role_label}）："
            "你刚才的回答触发了沙盘输出审查，请按下列要求重新组织一遍回答："
        ]
        if "meta_leak" in sources:
            lines.append("- 不要说你是 AI、语言模型或提及系统设定/剧本等元信息；完全以角色身份自然回应。")
        if "forbidden_phrase" in sources or "forbidden_pattern" in sources:
            lines.append("- 刚才发言包含被禁止输出的内容或措辞；请换一种完全不同的说法，且不得再触碰同类信息。")
        if "unknown_fact" in sources:
            lines.append("- 刚才你陈述了不在你知识范围内的事实。你不可能知道这些；请自然地表现出困惑、否认或反问，绝不要继续编造细节。")
        if "secret" in sources:
            lines.append("- 刚才你直接复述、引用或承认了绝密设定；你绝不能这样做。请用情绪化否认、反问、回避或转移话题的方式应对。")
        lines.append("- 只输出修正后的回答本身，不要解释、不要道歉、不要提及本次审查。")
        return "\n".join(lines)


__all__ = ["LeakGuard", "GuardAudit", "LeakFinding", "DEFAULT_META_PATTERNS", "normalize"]
