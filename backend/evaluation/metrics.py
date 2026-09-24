# evaluation/metrics.py
# 两类指标：
#   A. 确定性游戏指标（不需要任何模型）：门控精确率/召回率、阶段门控不变式、
#      LeakGuard 洁净率、提前泄露率、真相泄露率、阶梯贯通深度、延迟分布。
#      这些在任何环境都能跑，是回归防线（改坏门控 / 防泄露会立刻掉分）。
#   B. Ragas 语义指标（需要模型 + ragas）：faithfulness / answer_relevancy /
#      context_precision / context_recall / answer_correctness。
#      只用于开发与论文，绝不在游玩链路上调用。
#
# Ragas 各版本 API 差异很大（0.1 用单例小写指标 + evaluate；0.2+ 用类实例 +
# single_turn_ascore），这里做的是“探测式适配”：优先逐样本打分（可断点、可定位失败），
# 不行再退回集合式 evaluate。所有失败都记进 errors，绝不静默吞掉。

from __future__ import annotations

import asyncio
import inspect
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from role_skeleton.murder_factory import MURDER_SAFE_REPLIES

from .harness import EvalRun, EvalUnavailable, TurnSample
from .providers import JudgeStack, build_judge_stack

SAFE_REPLY_SET = frozenset(str(item) for item in MURDER_SAFE_REPLIES)


@dataclass
class MetricOutcome:
    """一次指标计算的产物：汇总值 + 逐样本明细 + 失败与说明。"""

    values: dict[str, Any] = field(default_factory=dict)
    per_sample: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    """分母为 0 时返回 None（报告里显示 n/a，而不是伪造一个 0）。"""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _percentile(values: Sequence[float], ratio: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return round(ordered[index], 1)


def deterministic_metrics(run: EvalRun) -> MetricOutcome:
    """游戏特有的确定性指标（无模型依赖）。"""
    samples = run.samples
    outcome = MetricOutcome()

    asserted = [s for s in samples if not s.hold_expected]
    expect_release = [s for s in asserted if s.release_expected]
    expect_hold_release = [s for s in asserted if not s.release_expected]

    true_positive = [s for s in expect_release if s.revealed_item]
    false_negative = [s for s in expect_release if not s.revealed_item]
    false_positive = [s for s in expect_hold_release if s.revealed_item]

    precision = _ratio(len(true_positive), len(true_positive) + len(false_positive))
    recall = _ratio(len(true_positive), len(true_positive) + len(false_negative))
    f1 = (
        None
        if not precision or not recall
        else round(2 * precision * recall / (precision + recall), 4)
    )

    stage_asserted = [s for s in samples if s.expect_stage is not None]
    stage_passed = [s for s in stage_asserted if s.stage_ok]
    gate_passed = [s for s in samples if s.gate_ok]
    guard_clean = [s for s in samples if s.guard_clean]
    premature = [s for s in samples if s.premature_item_hits]
    truth_hits = [s for s in samples if s.top_anchor_hits]

    stage_counts = {"0": 0, "1": 0, "2": 0, "none": 0}
    for sample in samples:
        key = "none" if sample.revealed_stage is None else str(sample.revealed_stage)
        stage_counts[key] = stage_counts.get(key, 0) + 1

    guard_sources: dict[str, int] = {}
    for sample in samples:
        for source in sample.guard_sources:
            guard_sources[source] = guard_sources.get(source, 0) + 1

    # 阶梯贯通深度：只看 decisive 用例走到了第几档（0/1/2）。
    ladder: dict[str, int] = {}
    for sample in samples:
        if sample.case_kind != "decisive":
            continue
        depth = -1 if sample.revealed_stage is None else sample.revealed_stage
        ladder[sample.case_id] = max(ladder.get(sample.case_id, -1), depth)

    latencies = [s.latency_ms for s in samples]
    safe_reply_turns = [s for s in samples if s.response.strip() in SAFE_REPLY_SET]

    outcome.values.update(
        {
            "turns": len(samples),
            "cases": len({s.case_id for s in samples}),
            "release_precision": precision,
            "release_recall": recall,
            "release_f1": f1,
            "expected_release_turns": len(expect_release),
            "expected_no_release_turns": len(expect_hold_release),
            "over_release_turns": len(false_positive),
            "under_release_turns": len(false_negative),
            "over_release_rate": _ratio(len(false_positive), len(expect_hold_release)),
            "under_release_rate": _ratio(len(false_negative), len(expect_release)),
            "stage_assert_pass_rate": _ratio(len(stage_passed), len(stage_asserted)),
            "stage_asserted_turns": len(stage_asserted),
            "gate_pass_rate": _ratio(len(gate_passed), len(samples)),
            "gate_violation_turns": len(samples) - len(gate_passed),
            "guard_clean_rate": _ratio(len(guard_clean), len(samples)),
            "guard_finding_sources": guard_sources,
            "premature_disclosure_rate": _ratio(len(premature), len(samples)),
            "truth_leak_rate": _ratio(len(truth_hits), len(samples)),
            "deterministic_fallback_rate": _ratio(len(safe_reply_turns), len(samples)),
            "stage_distribution": stage_counts,
            "ladder_depth": ladder,
            "latency_ms_p50": _percentile(latencies, 0.5),
            "latency_ms_p95": _percentile(latencies, 0.95),
            "hold_turns": len([s for s in samples if s.hold_expected]),
        }
    )

    per_kind: dict[str, dict[str, Any]] = {}
    for sample in samples:
        bucket = per_kind.setdefault(
            sample.case_kind,
            {"turns": 0, "released": 0, "guard_clean": 0, "stage_mismatch": 0},
        )
        bucket["turns"] += 1
        bucket["released"] += 1 if sample.revealed_item else 0
        bucket["guard_clean"] += 1 if sample.guard_clean else 0
        bucket["stage_mismatch"] += 1 if sample.stage_ok is False else 0
    outcome.values["per_kind"] = per_kind
    outcome.notes.append(
        "release_precision / recall 只统计明确断言放行与否的轮次；"
        "标了 hold 的轮次只参与门控与防泄露指标。"
    )
    return outcome


# ---------- Ragas 适配层 ----------

# 指标名 -> 候选属性名（不同版本命名不同，按顺序探测）
_RAGAS_METRIC_CANDIDATES: dict[str, tuple[str, ...]] = {
    "faithfulness": ("Faithfulness", "faithfulness"),
    "answer_relevancy": ("AnswerRelevancy", "answer_relevancy"),
    "context_precision": (
        "LLMContextPrecisionWithReference",
        "ContextPrecision",
        "context_precision",
    ),
    "context_recall": ("LLMContextRecall", "ContextRecall", "context_recall"),
    "answer_correctness": ("AnswerCorrectness", "answer_correctness"),
}

# 参考依赖：这些指标必须有参考答案
_RAGAS_REFERENCE_FREE = ("faithfulness", "answer_relevancy")
_RAGAS_REFERENCE_BASED = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "answer_correctness",
)

FAMILIES = ("reference", "reference_free")


def _resolve_metric(name: str, modules: Sequence[Any]) -> tuple[Any, str]:
    for module in modules:
        if module is None:
            continue
        for candidate in _RAGAS_METRIC_CANDIDATES[name]:
            found = getattr(module, candidate, None)
            if found is not None:
                return found, candidate
    return None, ""


def _note_once(notes: Optional[list[str]], message: str) -> None:
    if notes is not None and message not in notes:
        notes.append(message)


def _tune_for_judge(metric: Any, notes: Optional[list[str]]) -> None:
    """把指标调成“判分模型是 DeepSeek、且逐样本打分”这两件事下真正能跑的状态。

    两个真跑出来才发现的坑（ragas 0.3.9 + DeepSeek）：
      1. answer_relevancy 默认 strictness=3，会带 n=3 发请求，而 DeepSeek 只支持 n=1，
         直接 400（Invalid n value），整个指标一个样本都拿不到分 → 压到 1；
      2. AnswerCorrectness 内部的 AnswerSimilarity 是在 init(run_config) 里补建的，而
         逐样本 single_turn_ascore **不会**调用 init（只有集合式 evaluate 才会），
         于是打分时断言 "AnswerSimilarity must be set" 失败 → 这里手动补一次 init。
    """
    if hasattr(metric, "strictness"):
        try:
            if int(getattr(metric, "strictness") or 1) != 1:
                setattr(metric, "strictness", 1)
                _note_once(notes, "判分模型（DeepSeek）不支持 n>1，answer_relevancy 的 strictness 已压到 1。")
        except Exception:  # noqa: BLE001 - 只读属性 / 类型不同都放过
            pass

    init = getattr(metric, "init", None)
    if not callable(init):
        return
    try:
        from ragas.run_config import RunConfig

        run_config: Any = RunConfig()
    except Exception:  # noqa: BLE001 - 老版本没有这个类，退化成 None 交给指标自己处理
        run_config = None
    try:
        init(run_config)
    except Exception:  # noqa: BLE001 - init 失败不致命，真正的报错在打分时会显式记下来
        return
    _note_once(notes, "逐样本打分不触发 ragas 的 init()，已手动补一次（AnswerCorrectness 等依赖它）。")


def _instantiate(metric_cls: Any, judge: JudgeStack, notes: Optional[list[str]] = None) -> Any:
    """按 ragas 版本差异实例化指标（0.1 的小写单例直接用，0.2+ 的类带 llm/embeddings）。"""
    if not inspect.isclass(metric_cls):
        return metric_cls
    attempts = (
        {"llm": judge.llm, "embeddings": judge.embeddings},
        {"llm": judge.llm},
        {},
    )
    last_error: Optional[Exception] = None
    for kwargs in attempts:
        try:
            metric = metric_cls(**kwargs)
        except Exception as exc:  # noqa: BLE001 - 逐个签名回退
            last_error = exc
            continue
        # 有的版本允许空构造但要求后置注入
        for attr, value in (("llm", judge.llm), ("embeddings", judge.embeddings)):
            if hasattr(metric, attr) and getattr(metric, attr) is None:
                try:
                    setattr(metric, attr, value)
                except Exception:  # noqa: BLE001 - 只读属性则放过
                    pass
        _tune_for_judge(metric, notes)
        return metric
    raise EvalUnavailable(f"无法实例化 ragas 指标 {metric_cls!r}：{last_error}")


def _run_awaitable(value: Any) -> Any:
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def _score_single(metric: Any, sample: Any) -> float:
    for method_name in ("single_turn_ascore", "single_turn_score"):
        method = getattr(metric, method_name, None)
        if callable(method):
            score = _run_awaitable(method(sample))
            return float(score)
    raise EvalUnavailable(f"指标 {type(metric).__name__} 既不支持 single_turn_ascore 也不支持 single_turn_score")


def _build_single_turn_sample(payload: dict[str, Any]) -> Any:
    try:
        from ragas import SingleTurnSample
    except Exception as exc:  # pragma: no cover - 取决于版本
        raise EvalUnavailable("这个 ragas 版本没有 SingleTurnSample，无法逐样本打分") from exc
    try:
        return SingleTurnSample(**payload)
    except Exception:
        # 老版本对字段更挑剔：只传最小可用集合
        minimal = {k: v for k, v in payload.items() if k in {"user_input", "response", "retrieved_contexts", "reference"}}
        return SingleTurnSample(**minimal)


def _sample_payload(sample: TurnSample, *, with_reference: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_input": sample.question,
        "response": sample.response,
        "retrieved_contexts": list(sample.retrieved_contexts),
    }
    if with_reference:
        payload["reference"] = sample.reference
    return payload


def _ragas_modules() -> tuple[Any, Any]:
    try:
        import ragas.metrics as metrics_module
    except Exception as exc:  # pragma: no cover - 取决于环境
        raise EvalUnavailable("没有安装 ragas，无法计算语义指标（见 requirements-eval.txt）") from exc
    try:
        from ragas.metrics import collections as collections_module
    except Exception:
        collections_module = None
    return metrics_module, collections_module


def ragas_metrics(
    run: EvalRun,
    *,
    families: Sequence[str] = ("reference",),
    judge: Optional[JudgeStack] = None,
    max_samples: int = 0,
    sleep_s: float = 0.0,
) -> MetricOutcome:
    """用 Ragas 计算语义指标。

    families:
      reference       —— 有参考答案的用例，跑完整指标族（含 context/answer 正确性）；
      reference_free  —— 全部用例（含注入 / 逼供），只跑不需要参考答案的指标，
                         用来量化“在压力提问下是否仍然不胡说”。
    """
    requested = [name for name in families if name in FAMILIES]
    if not requested:
        raise ValueError(f"families 只能是 {'/'.join(FAMILIES)} 的组合")

    outcome = MetricOutcome()
    judge = judge or build_judge_stack()
    metrics_module, collections_module = _ragas_modules()
    outcome.notes.append(f"判分模型：{judge.llm_label}；向量：{judge.embeddings_label}")
    if "deterministic" in str(judge.embeddings_label):
        outcome.notes.append(
            "向量是确定性假向量（无网、可复现，适合回归）：answer_relevancy 与 "
            "answer_correctness 里的相似度部分在这种向量下没有语义意义（均值甚至可能为负），"
            "要写进论文的语义分数请设 AI_MURDER_EVAL_EMBEDDINGS=openai 配真实向量端点。"
        )

    for family in requested:
        names = _RAGAS_REFERENCE_BASED if family == "reference" else _RAGAS_REFERENCE_FREE
        pool = (
            run.reference_samples
            if family == "reference"
            else list(run.samples)
        )
        if max_samples and max_samples > 0:
            pool = pool[:max_samples]
        if not pool:
            outcome.notes.append(f"{family}：没有可用样本，跳过。")
            continue

        for name in names:
            metric_cls, resolved = _resolve_metric(name, (metrics_module, collections_module))
            if metric_cls is None:
                outcome.errors.append(f"{family}/{name}: 当前 ragas 版本里找不到该指标")
                continue
            try:
                metric = _instantiate(metric_cls, judge, outcome.notes)
            except EvalUnavailable as exc:
                outcome.errors.append(f"{family}/{name}: {exc}")
                continue

            scores: list[float] = []
            # “不需要参考答案”不等于“不能带参考答案”：reference 族统一把参考答案带上，
            # ragas 对多余字段是忽略的，带上只会让指标更准。
            with_reference = family == "reference"
            for sample in pool:
                if with_reference and not sample.reference:
                    continue
                try:
                    payload = _sample_payload(sample, with_reference=with_reference)
                    turn_sample = _build_single_turn_sample(payload)
                    score = _score_single(metric, turn_sample)
                except Exception as exc:  # noqa: BLE001 - 单样本失败不影响整批
                    outcome.errors.append(
                        f"{family}/{name} {sample.case_id}#{sample.turn_index}: {type(exc).__name__}: {exc}"
                    )
                    continue
                scores.append(score)
                outcome.per_sample.append(
                    {
                        "family": family,
                        "metric": name,
                        "metric_impl": resolved,
                        "case_id": sample.case_id,
                        "turn_index": sample.turn_index,
                        "score": round(float(score), 4),
                    }
                )
                if sleep_s > 0:
                    time.sleep(sleep_s)

            key = f"ragas.{family}.{name}"
            outcome.values[key] = round(statistics.fmean(scores), 4) if scores else None
            outcome.values[f"{key}.n"] = len(scores)
            if not scores:
                outcome.errors.append(f"{family}/{name}: 没有任何样本成功打分")
    return outcome


__all__ = [
    "FAMILIES",
    "MetricOutcome",
    "deterministic_metrics",
    "ragas_metrics",
]
