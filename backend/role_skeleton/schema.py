# schema.py
# 角色硬约束骨架层 —— 数据结构
#
# 设计要点：
# - RoleSkeleton 描述 Agent 的“静态骨架”：身份、私密设定、受保护秘密、时间线、
#   知识边界、底线与禁止输出清单。它由剧本作者 / 沙盘设计者或引擎规则生成，
#   属于“不可篡改”部分。
# - 深度不可变：模型全部 frozen，且所有容器一律用 tuple 存储（构造时由 list 自动
#   转换）。不仅大模型没有写入入口，连 Python 代码也无法原地改写任何一层。
# - “动态对话层”（怎么说话、用什么语气表达）不属于骨架，由调用方组合。

from __future__ import annotations

from typing import Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_tuple(value) -> Tuple:
    """构造时把 list 容器统一转成 tuple，实现深层不可变。"""
    if value is None:
        return ()
    return tuple(value)


class Secret(BaseModel):
    """一个受保护秘密：模型为了保持自洽必须“知道”它，但严禁向任何人输出。"""

    model_config = ConfigDict(frozen=True)

    title: str = Field(description="秘密的标题，例如：真实身份、价格底线")
    content: str = Field(description="秘密内容")
    reveal_condition: str = Field(
        default="",
        description="允许被合法揭示的条件；只能由引擎判定，不由模型自行判断",
    )
    holders: Tuple[str, ...] = Field(
        default_factory=tuple,
        description="允许知情的 agent_id；为空表示仅本角色自己",
    )

    @field_validator("holders", mode="before")
    @classmethod
    def _holders_to_tuple(cls, value):
        return _to_tuple(value)


class KnowledgeBoundary(BaseModel):
    """知识边界。

    known   —— 角色“可以知道并能正常谈论”的事实，会渲染进只读骨架 prompt。
    unknown —— 角色“不该知道”的事实。永远不渲染给大模型，只作为防泄露检测语料
               （防止模型脑补/幻觉时恰好“编”出不该知道的内容，也用于事后审计）。
    """

    model_config = ConfigDict(frozen=True)

    known: Tuple[str, ...] = Field(default_factory=tuple)
    unknown: Tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("known", "unknown", mode="before")
    @classmethod
    def _lists_to_tuple(cls, value):
        return _to_tuple(value)


class TimelineEvent(BaseModel):
    """一条时间线事件（角色自己的行动线 / 口径线）。"""

    model_config = ConfigDict(frozen=True)

    when: str = Field(default="", description="时间/节点")
    what: str = Field(default="", description="发生了什么")
    public: bool = Field(default=False, description="是否属于对外可公开的时间线")
    alibi: bool = Field(default=False, description="是否是需要对外咬住的不在场/口径事件")


class SkeletonPolicy(BaseModel):
    """骨架硬规则。

    bottom_lines 等“规则描述”会渲染进 prompt；forbidden_* 只用于输出检测，
    绝不把清单原文渲染给大模型（避免教模型如何绕开措辞）。
    """

    model_config = ConfigDict(frozen=True)

    bottom_lines: Tuple[str, ...] = Field(
        default_factory=tuple,
        description="底线：任何情况下都不得违反的行为约束（渲染进 prompt）",
    )
    forbidden_phrases: Tuple[str, ...] = Field(
        default_factory=tuple,
        description="禁止输出清单（字面短语）。只用于输出检测，不渲染进 prompt",
    )
    forbidden_patterns: Tuple[str, ...] = Field(
        default_factory=tuple,
        description="禁止输出清单（正则）。只用于输出检测，不渲染进 prompt",
    )
    meta_leak_patterns: Tuple[str, ...] = Field(
        default_factory=tuple,
        description="出戏话术（察觉自己是 AI / 复述系统设定等）正则，附加到内置默认检测",
    )

    @field_validator(
        "bottom_lines",
        "forbidden_phrases",
        "forbidden_patterns",
        "meta_leak_patterns",
        mode="before",
    )
    @classmethod
    def _lists_to_tuple(cls, value):
        return _to_tuple(value)


class RoleSkeleton(BaseModel):
    """角色静态骨架。构造完成后即深度冻结，任何写入尝试都会抛错。"""

    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(description="引擎内唯一标识")
    display_name: str = Field(description="角色姓名/称呼")
    role_label: str = Field(default="", description="角色标签：凶手/采购方/销售方……")
    public_profile: str = Field(default="", description="公开人设，可向任何人介绍")

    private_facts: Tuple[str, ...] = Field(
        default_factory=tuple,
        description="私密设定：仅供角色自己把握言行，绝不对外输出",
    )
    secrets: Tuple[Secret, ...] = Field(default_factory=tuple)
    timeline: Tuple[TimelineEvent, ...] = Field(default_factory=tuple)

    knowledge: KnowledgeBoundary = Field(default_factory=KnowledgeBoundary)
    policy: SkeletonPolicy = Field(default_factory=SkeletonPolicy)

    @field_validator("private_facts", "secrets", "timeline", mode="before")
    @classmethod
    def _lists_to_tuple(cls, value):
        return _to_tuple(value)


__all__ = [
    "RoleSkeleton",
    "Secret",
    "KnowledgeBoundary",
    "TimelineEvent",
    "SkeletonPolicy",
]
