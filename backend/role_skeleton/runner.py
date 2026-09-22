# runner.py
# 角色骨架层 —— 受限生成执行器
#
# 把“动态对话层”的生成纳入强制闭环：
#   generate() -> LeakGuard.audit() -> clean 则通过
#                 -> 有违规则把类别化修正指引(steering)回灌模型，重新生成（最多 max_retry 次）
#                 -> 仍不通过则使用确定性兜底发言（fallback），保证绝不放行违规文本。

from __future__ import annotations

from typing import Callable, List, Optional

from pydantic import BaseModel, Field

from .guard import GuardAudit, LeakFinding, LeakGuard
from .schema import RoleSkeleton


class RoundRecord(BaseModel):
    """一次生成-审查记录，用于审计与调试。"""

    attempt: int
    clean: bool
    finding_count: int
    sources: List[str] = Field(default_factory=list)
    used_fallback: bool = False
    text_preview: str = Field(default="")


def constrained_answer(
    skeleton: RoleSkeleton,
    generate: Callable[[Optional[str]], str],
    *,
    max_retry: int = 2,
    fallback: Optional[Callable[[], str]] = None,
) -> tuple[str, List[RoundRecord]]:
    """在骨架约束下执行一次回答。

    generate(steering) 负责真正调用 LLM：
    - 第一次调用 steering=None；
    - 若文本未通过审查，之后传入类别化修正指引重新生成。
    返回 (最终文本, 逐轮审查记录)。
    """

    guard = LeakGuard(skeleton)
    records: List[RoundRecord] = []
    steering: Optional[str] = None
    last_text = ""

    for attempt in range(max_retry + 1):
        text = (generate(steering) or "").strip()
        last_text = text
        audit: GuardAudit = guard.audit(text)
        records.append(
            RoundRecord(
                attempt=attempt,
                clean=audit.clean,
                finding_count=len(audit.findings),
                sources=audit.sources,
                text_preview=text[:60],
            )
        )
        if audit.clean:
            return text, records
        steering = guard.build_steering(audit.findings)

    if fallback is not None:
        fallback_text = (fallback() or "").strip()
        records.append(
            RoundRecord(
                attempt=max_retry + 1,
                clean=True,
                finding_count=0,
                used_fallback=True,
                text_preview=fallback_text[:60],
            )
        )
        return fallback_text, records

    return last_text, records


__all__ = ["constrained_answer", "RoundRecord"]
