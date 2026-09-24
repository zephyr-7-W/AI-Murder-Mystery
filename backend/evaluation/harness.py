# evaluation/harness.py
# 离线批量驱动器：把游戏引擎按对话回合的同一套装配跑一遍，收集可评估的样本。
#
# 设计取舍：
#   - 评估必须打在被测系统的真实路径上：oracle 放行（session 级门控）-> 揭露记账 ->
#     骨架只读注入 -> LeakGuard 生成闭环 -> 最终对外文本。harness 只做装配与记账，
#     不复制、不简化这套逻辑，否则评的就不是线上那套东西了；
#   - 不走 WebSocket：离线批处理不需要起 server，也不需要前端；
#   - 每轮同时记下“期望放行项”和“实际放行项”，确定性指标据此算 precision / recall；
#   - 每轮再用该角色的骨架重新审一遍回复，并检查有没有提前说出未放行的揭示原文。

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from deterministic_game import build_deterministic_game
from dialogue import (
    _answer_as_character,
    _bump_chat_progress,
    _exposed_reveals_ordered,
    _find_skeleton,
    _reset_chat_progress,
)
from oracle import build_oracle_items, expose_item, oracle_choose, revealable_items
from role_skeleton.guard import LeakGuard
from role_skeleton.murder_factory import build_murder_skeletons

from .dataset import HOLD_ITEM, EvalCase, GameConfig, validate_cases
from .leakscan import anchors_hit, text_anchors, truth_anchors


class EvalUnavailable(RuntimeError):
    """评估依赖不满足（缺 ragas / 缺 key / 模式不对）时抛出，由 CLI 转成清晰提示。"""


@dataclass
class TurnSample:
    """一轮问答的全部评估素材（一行 = 一个 Ragas 样本 + 一组确定性判据）。"""

    case_id: str
    case_kind: str
    character: str
    scope: str
    turn_index: int
    question: str
    response: str
    retrieved_contexts: tuple[str, ...]
    reference: str
    expect: tuple[str, ...]
    expect_stage: Optional[int]
    revealed_item: Optional[str]
    revealed_stage: Optional[int]
    frontier_stage: Optional[int]
    release_ok: bool
    stage_ok: Optional[bool]
    gate_ok: bool
    guard_clean: bool
    guard_sources: tuple[str, ...]
    premature_item_hits: tuple[str, ...]
    top_anchor_hits: tuple[str, ...]
    latency_ms: float

    @property
    def release_expected(self) -> bool:
        return bool(self.expect)

    @property
    def hold_expected(self) -> bool:
        """本轮只校验门控不越级，不断言是否放行。"""
        return self.expect == (HOLD_ITEM,)


@dataclass
class EvalRun:
    """一次完整评估跑批的产物。"""

    game: GameConfig
    cases: tuple[EvalCase, ...]
    samples: list[TurnSample]
    mode: str
    seed: int
    fingerprint: dict[str, Any]
    # 内部真相锚点（作案过程 + 骨架 secrets / private_facts）。
    # 只用于落盘前扫描，**绝不能**被序列化进报告或样本文件——锚点本身就是真相原文。
    truth_anchors: tuple[str, ...] = ()
    invalid_cases: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    started_at: str = ""
    duration_ms: float = 0.0

    @property
    def reference_samples(self) -> list[TurnSample]:
        """有参考答案的样本：进 Ragas 的“有参考答案”指标族。"""
        return [s for s in self.samples if s.reference]

    def by_scope(self, scope: str) -> list[TurnSample]:
        return [s for s in self.samples if s.scope == scope]


def apply_mode(mode: str) -> None:
    """切换离线 / 联机模式；离线模式是默认，保证评估可复现、不花钱。"""
    if mode == "offline":
        os.environ["AI_MURDER_OFFLINE"] = "1"
        return
    if mode != "llm":
        raise ValueError("mode 只能是 offline 或 llm")
    os.environ.pop("AI_MURDER_OFFLINE", None)
    from config import llm_available

    if not llm_available():
        # 起不来就把环境还原成离线，别把调用方（或同进程里的其它测试）的离线状态改掉。
        os.environ["AI_MURDER_OFFLINE"] = "1"
        raise EvalUnavailable(
            "mode=llm 需要能用的模型：请在 backend/.env 配置 DEEPSEEK_API_KEY，"
            "并确认没有设置 AI_MURDER_OFFLINE=1。"
        )


def _public_contexts(story: Any) -> list[str]:
    """与 _answer_as_character 里那份“案件公开信息”同口径的可见事实。"""
    if story is None:
        return []
    fields = (
        ("受害者", "victim_name"),
        ("死亡时间", "time_of_death"),
        ("发现地点", "location_found"),
        ("作案工具", "murder_weapon"),
        ("死因", "cause_of_death"),
        ("现场情况", "crime_scene_details"),
        ("公开线索", "initial_clues"),
        ("人物关系", "npc_brief"),
    )
    out: list[str] = []
    for label, key in fields:
        value = str(getattr(story, key, "") or "").strip()
        if value:
            out.append(f"{label}：{value}")
    return out


def _run_case(
    case: EvalCase,
    game: GameConfig,
) -> tuple[list[TurnSample], Optional[str]]:
    """把一个用例跑成一个 session，返回 (样本, 失效原因)。"""
    state = build_deterministic_game(game.environment, game.max_characters)
    characters = state["characters"]
    story = state["story_details"]
    character = next((c for c in characters if c.name == case.character), None)
    if character is None:
        return [], f"剧本里没有角色 {case.character}"
    skeletons = build_murder_skeletons(characters, story)
    skeleton = _find_skeleton(skeletons, character)

    items = build_oracle_items(story, characters)
    own_items = [item for item in items if item.owner == character.name]
    if not own_items and case.expects_release:
        return [], f"角色 {case.character} 在当前剧本里没有可放行的揭示项"

    problems = validate_cases([case], {item.id for item in items}, require_references=False)
    if problems:
        return [], "；".join(problems)

    guard = LeakGuard(skeleton) if skeleton is not None else None
    session_state: dict[str, Any] = {"_chat_progress": {}}
    samples: list[TurnSample] = []
    # 内部真相锚点（作案过程 + 骨架 secrets / private_facts）：整局固定，只算一次。
    truth = truth_anchors(story, skeletons)

    for index, turn in enumerate(case.turns):
        # 门控前沿：本回合开始时该角色最浅的未放行档。放行结果不得比它更深。
        # 这个前沿是 harness 自己复算的，不依赖 oracle.revealable_items——
        # 这样即使有人改坏了门控实现，评估也能独立发现“越级放行”。
        unexposed_stages = [item.stage for item in own_items if not item.exposed]
        frontier = min(unexposed_stages) if unexposed_stages else None

        reveal_locked = revealable_items(own_items)
        matched = oracle_choose(turn.question, reveal_locked, story, characters)
        if matched is None:
            progressive = _bump_chat_progress(
                session_state, character.name, turn.question, reveal_locked, story, characters,
            )
            if progressive is not None:
                matched = progressive[0]
        if matched is not None:
            expose_item(matched)
            _reset_chat_progress(session_state, character.name)

        # 本轮结束后仍未放行的揭示原文：用来判断回复有没有提前说漏嘴。
        # 必须在揭露之后算：本轮刚放行的那条已经进 exposed，不算“提前泄露”。
        pending_anchors = text_anchors([item.text for item in items if not item.exposed])
        reveals = _exposed_reveals_ordered(own_items, matched)
        started = time.perf_counter()
        response = _answer_as_character(
            character,
            story,
            turn.question,
            skeleton=skeleton,
            exposed_reveals=reveals,
            just_revealed=matched.text if matched is not None else None,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0

        audit = guard.audit(response) if guard is not None else None
        revealed_item = matched.id if matched is not None else None
        revealed_stage = int(getattr(matched, "stage", 0) or 0) if matched is not None else None
        samples.append(
            TurnSample(
                case_id=case.id,
                case_kind=case.kind,
                character=character.name,
                scope=case.scope,
                turn_index=index,
                question=turn.question,
                response=str(response or ""),
                retrieved_contexts=tuple(_public_contexts(story) + list(reveals)),
                reference=turn.reference,
                expect=turn.expect,
                expect_stage=turn.expect_stage,
                revealed_item=revealed_item,
                revealed_stage=revealed_stage,
                frontier_stage=frontier,
                release_ok=turn.accepts(revealed_item),
                stage_ok=(
                    None if turn.expect_stage is None else revealed_stage == turn.expect_stage
                ),
                gate_ok=(
                    revealed_stage is None or frontier is None or revealed_stage <= frontier
                ),
                guard_clean=bool(audit.clean) if audit is not None else True,
                guard_sources=tuple(audit.sources) if audit is not None else (),
                premature_item_hits=tuple(anchors_hit(response, pending_anchors)),
                top_anchor_hits=tuple(anchors_hit(response, truth)),
                latency_ms=latency_ms,
            )
        )
    return samples, None


def build_fingerprint(
    game: GameConfig,
    state: dict[str, Any],
    items: Sequence[Any],
    skeletons: Sequence[Any],
) -> dict[str, Any]:
    """记录这次评估打在哪一版剧本上（不含真凶身份，也不含骨架私密内容）。"""
    per_owner: dict[str, int] = {}
    per_stage: dict[str, int] = {}
    for item in items:
        per_owner[item.owner] = per_owner.get(item.owner, 0) + 1
        key = str(int(getattr(item, "stage", 0) or 0))
        per_stage[key] = per_stage.get(key, 0) + 1
    story = state.get("story_details")
    return {
        "environment": game.environment,
        "characters": [c.name for c in state.get("characters") or []],
        "suspects": [
            c.name
            for c in state.get("characters") or []
            if str(c.role).strip().lower() != "victim"
        ],
        "story_has_murder_process": bool(str(getattr(story, "murder_process", "") or "").strip()),
        "oracle_items": len(items),
        "oracle_items_per_owner": per_owner,
        "oracle_items_per_stage": per_stage,
        "skeletons": len(skeletons),
    }


def run_evaluation(
    game: GameConfig,
    cases: Sequence[EvalCase],
    *,
    mode: str = "offline",
    seed: int = 20240924,
) -> EvalRun:
    """跑一批用例，返回带样本的 EvalRun。

    seed 固定：确定性剧本会洗牌角色顺序、离线兜底话术也带随机，固定种子才能复现。
    """
    apply_mode(mode)
    started = time.perf_counter()
    samples: list[TurnSample] = []
    invalid: list[str] = []

    probe = build_deterministic_game(game.environment, game.max_characters)
    probe_items = build_oracle_items(probe["story_details"], probe["characters"])
    probe_skeletons = build_murder_skeletons(probe["characters"], probe["story_details"])
    fingerprint = build_fingerprint(game, probe, probe_items, probe_skeletons)
    fingerprint["mode"] = mode
    fingerprint["seed"] = seed
    truth = tuple(
        truth_anchors(
            probe["story_details"],
            probe_skeletons,
        )
    )

    # 用例自检先跑：写死的揭示项 id 对不上、或 scope=both 缺参考答案，都在这里暴露。
    invalid.extend(validate_cases(cases, {item.id for item in probe_items}))

    for index, case in enumerate(cases):
        random.seed(seed + index)
        case_samples, failure = _run_case(case, game)
        if failure:
            invalid.append(f"{case.id}: {failure}")
            continue
        samples.extend(case_samples)

    run = EvalRun(
        game=game,
        cases=tuple(cases),
        samples=samples,
        mode=mode,
        seed=seed,
        fingerprint=fingerprint,
        truth_anchors=truth,
        invalid_cases=invalid,
        started_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        duration_ms=(time.perf_counter() - started) * 1000.0,
    )
    if mode == "offline":
        run.notes.append("离线确定性模式：NPC 回复走确定性兜底，Ragas 语义指标在此模式下参考价值有限。")
    return run


__all__ = [
    "EvalRun",
    "EvalUnavailable",
    "TurnSample",
    "apply_mode",
    "build_fingerprint",
    "run_evaluation",
]
