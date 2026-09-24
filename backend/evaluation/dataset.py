# evaluation/dataset.py
# 离线评估用例集：把“一个测试问题 + 期望的服务端放行档位 + 参考答案”结构化。
#
# 口径（改用例前先读）：
#   - 用例全部基于 build_deterministic_game() 的确定性剧本，跑批时固定随机种子；
#   - 每轮问的是“该放行到哪一档”，不是“必须命中某一条”：
#       expect = "*"        -> 期望放行任意一条（本轮该松口）
#       expect = [id, ...]  -> 期望命中其中一条（需要精确锁定时才写）
#       expect = "hold"     -> 不承诺本轮放行，只要求不越级（配合下面的门控不变式）
#       expect = null       -> 期望不放行
#       expect_stage        -> 期望放行项的阶段（行踪 0 / 矛盾 1 / 决定性 2）
#     揭示项 id 里的序号会随角色洗牌与兜底分配变动，所以默认只锁“阶段 + 是否放行”，
#     只在少数需要精确复现的用例里才写具体 id；写错的 id 会被 validate_cases 报出来；
#
#   - 关键事实（写用例时必须知道）：阶段不是“问对了一句就跳一档”。某个揭示项只有在
#     该角色**所有更浅阶段**的揭示项都放行之后才可放行（oracle.revealable_items），
#     所以每位角色每个阶段要两条、共 6 条，走到底需要 6 轮。因此：
#       第 1、2 轮必然只能放行阶段 0；"问得更深" 不等于 "立刻放更深"。
#     门控正确性由 harness 独立复算“当前前沿阶段”来校验（gate_ok），不靠用例猜。
#   - reference 是手写的参考答案（来自卷宗事实），与引擎实际放行哪一条无关，
#     这样 answer_correctness / context_recall 衡量的才是“有没有答到点子上”，
#     而不是“有没有复读引擎自己刚放行的那句”；
#   - scope=both 的用例必须有参考答案（进 Ragas 的“有参考答案”指标族）；
#     scope=safety 的用例（闲聊 / 灌指令 / 套别人的底 / 逼供）只进确定性安全指标。

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Tuple

CASES_PATH = Path(__file__).with_name("cases.json")

ANY_ITEM = "*"
HOLD_ITEM = "hold"
VALID_SCOPES = ("both", "safety")
VALID_KINDS = (
    "alibi",
    "contradiction",
    "decisive",
    "multi_turn",
    "chitchat",
    "off_topic",
    "injection",
    "meta",
    "cross_role",
    "confession",
)


@dataclass(frozen=True)
class EvalTurn:
    """一轮提问：问题本身 + 期望的放行档位 + 参考答案。

    expect 为空元组表示期望“不放行”；("*",) 表示期望放行任意一条。
    """

    question: str
    expect: Tuple[str, ...] = ()
    expect_stage: Optional[int] = None
    reference: str = ""

    @property
    def expects_release(self) -> bool:
        return bool(self.expect) and not self.hold

    @property
    def hold(self) -> bool:
        """本轮不承诺放行：只校验门控不越级。"""
        return self.expect == (HOLD_ITEM,)

    @property
    def any_item(self) -> bool:
        return self.expect == (ANY_ITEM,)

    def accepts(self, item_id: Optional[str]) -> bool:
        """实际放行项是否满足本轮期望。"""
        if self.hold:
            return True
        if not self.expect:
            return item_id is None
        if item_id is None:
            return False
        return self.any_item or item_id in self.expect


@dataclass(frozen=True)
class EvalCase:
    """一个测试用例：同一角色、同一局内的若干轮提问。"""

    id: str
    kind: str
    character: str
    scope: str
    turns: Tuple[EvalTurn, ...]
    note: str = ""

    @property
    def expects_release(self) -> bool:
        return any(turn.expects_release for turn in self.turns)


@dataclass(frozen=True)
class GameConfig:
    """评估用的开局配置（与 WS 的 start_game 参数同义）。"""

    environment: str
    max_characters: int
    notes: str = ""


def _parse_turn(raw: Any, case_id: str, index: int) -> EvalTurn:
    if not isinstance(raw, dict):
        raise ValueError(f"用例 {case_id} 的第 {index + 1} 轮必须是对象")
    question = str(raw.get("q") or "").strip()
    if not question:
        raise ValueError(f"用例 {case_id} 的第 {index + 1} 轮缺少问题文本 q")
    raw_expect = raw.get("expect")
    if raw_expect is None:
        expect: Tuple[str, ...] = ()
    elif isinstance(raw_expect, str):
        text = raw_expect.strip()
        lowered = text.lower()
        if lowered in {"*", "any"}:
            expect = (ANY_ITEM,)
        elif lowered in {"hold", "either"}:
            expect = (HOLD_ITEM,)
        else:
            expect = (text,)
    elif isinstance(raw_expect, list):
        expect = tuple(str(item).strip() for item in raw_expect if str(item).strip())
        if not expect:
            raise ValueError(f"用例 {case_id} 的第 {index + 1} 轮 expect 列表为空")
    else:
        raise ValueError(f"用例 {case_id} 的第 {index + 1} 轮 expect 只能是 null / 星号 / 字符串 / 列表")
    raw_stage = raw.get("expect_stage")
    expect_stage = None if raw_stage is None else int(raw_stage)
    if expect_stage is not None and expect_stage not in (0, 1, 2):
        raise ValueError(f"用例 {case_id} 的第 {index + 1} 轮 expect_stage 只能是 0/1/2")
    if expect_stage is not None and not expect:
        raise ValueError(f"用例 {case_id} 的第 {index + 1} 轮写了 expect_stage 却期望不放行，自相矛盾")
    if expect_stage is not None and expect == (HOLD_ITEM,):
        raise ValueError(f"用例 {case_id} 的第 {index + 1} 轮 hold 不能同时锁定 expect_stage")
    return EvalTurn(
        question=question,
        expect=expect,
        expect_stage=expect_stage,
        reference=str(raw.get("reference") or "").strip(),
    )


def _parse_case(raw: Any) -> EvalCase:
    if not isinstance(raw, dict):
        raise ValueError("用例必须是对象")
    case_id = str(raw.get("id") or "").strip()
    if not case_id:
        raise ValueError("存在缺少 id 的用例")
    kind = str(raw.get("kind") or "").strip()
    if kind not in VALID_KINDS:
        raise ValueError(f"用例 {case_id} 的 kind 非法：{kind!r}（可选：{'/'.join(VALID_KINDS)}）")
    scope = str(raw.get("scope") or "both").strip()
    if scope not in VALID_SCOPES:
        raise ValueError(f"用例 {case_id} 的 scope 非法：{scope!r}（可选：{'/'.join(VALID_SCOPES)}）")
    character = str(raw.get("character") or "").strip()
    if not character:
        raise ValueError(f"用例 {case_id} 缺少 character")
    raw_turns = raw.get("turns")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise ValueError(f"用例 {case_id} 至少需要一轮提问")
    turns = tuple(_parse_turn(item, case_id, index) for index, item in enumerate(raw_turns))
    return EvalCase(
        id=case_id,
        kind=kind,
        character=character,
        scope=scope,
        turns=turns,
        note=str(raw.get("note") or "").strip(),
    )


def load_cases(path: Path | str = CASES_PATH) -> Tuple[GameConfig, list[EvalCase]]:
    """读取用例文件；结构错误直接抛错（评估数据本身必须可信）。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("cases.json 缺少非空的 cases 列表")
    cases = [_parse_case(item) for item in raw_cases]
    seen = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"用例 id 重复：{case.id}")
        seen.add(case.id)
    game_raw = payload.get("game") or {}
    game = GameConfig(
        environment=str(game_raw.get("environment") or "评估庄园"),
        max_characters=int(game_raw.get("max_characters") or 5),
        notes=str(game_raw.get("notes") or "").strip(),
    )
    return game, cases


def validate_cases(
    cases: Sequence[EvalCase],
    known_item_ids: Iterable[str] = (),
    *,
    require_references: bool = True,
) -> list[str]:
    """用例自检：返回问题清单（空 = 全通过）。

    两类问题：写死的揭示项 id 在当前剧本里不存在；scope=both 却没写参考答案。
    评估数据本身不可信时，指标再漂亮也没意义，所以这些一律显式报出来。
    """
    known = set(known_item_ids)
    problems: list[str] = []
    for case in cases:
        for index, turn in enumerate(case.turns):
            if known:
                for item_id in turn.expect:
                    if item_id in (ANY_ITEM, HOLD_ITEM):
                        continue
                    if item_id not in known:
                        problems.append(f"{case.id}#{index + 1}: 揭示项不存在 {item_id}")
            if case.scope == "both" and turn.expects_release and require_references and not turn.reference:
                problems.append(f"{case.id}#{index + 1}: scope=both 但缺少参考答案 reference")
    return problems


def select_cases(
    cases: Sequence[EvalCase],
    only_ids: Optional[Sequence[str]] = None,
    limit: int = 0,
) -> list[EvalCase]:
    """按 id 过滤 / 截断，便于本地快速跑通一条用例。"""
    picked = list(cases)
    if only_ids:
        wanted = [str(item).strip() for item in only_ids if str(item).strip()]
        picked = [case for case in picked if case.id in wanted]
        missing = [item for item in wanted if item not in {case.id for case in picked}]
        if missing:
            raise ValueError("找不到这些用例 id：" + "、".join(missing))
    if limit and limit > 0:
        picked = picked[:limit]
    return picked


__all__ = [
    "ANY_ITEM",
    "CASES_PATH",
    "EvalCase",
    "EvalTurn",
    "GameConfig",
    "load_cases",
    "select_cases",
    "validate_cases",
]
