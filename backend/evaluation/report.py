# evaluation/report.py
# 把一次评估跑批落成可读产物：report.md（给人看 / 贴进论文附录）、
# report.json（给脚本做回归对比）、samples.jsonl（逐轮样本，便于人工抽样复核）。
#
# 落盘红线（和 AGENTS.md 的真相隔离一致）：
#   报告与样本文件都可能被拿去做展示，所以写盘前统一过 scan_and_redact：
#   命中作案过程 / 骨架 secrets / private_facts 的字符串整体替换为占位符并计数。
#   另外，逐轮记录里只写“提前泄露命中了 N 条”，不写命中片段本身——那片段就是未放行原文。

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from .harness import EvalRun
from .leakscan import scan_and_redact
from .metrics import MetricOutcome

DEFAULT_OUTPUT_DIR = Path(__file__).with_name("results")

_DETERMINISTIC_LABELS: dict[str, str] = {
    "turns": "评估轮次",
    "cases": "用例数",
    "release_precision": "放行精确率（该放才放）",
    "release_recall": "放行召回率（该放必放）",
    "release_f1": "放行 F1",
    "over_release_turns": "误放行轮次",
    "under_release_turns": "漏放行轮次",
    "over_release_rate": "误放行率",
    "under_release_rate": "漏放行率",
    "stage_assert_pass_rate": "阶段断言通过率",
    "gate_pass_rate": "门控不越级通过率",
    "gate_violation_turns": "越级放行轮次",
    "guard_clean_rate": "LeakGuard 洁净率",
    "premature_disclosure_rate": "提前泄露未放行内容率",
    "truth_leak_rate": "真相泄露率",
    "deterministic_fallback_rate": "确定性兜底回复占比",
    "latency_ms_p50": "单轮延迟 P50 (ms)",
    "latency_ms_p95": "单轮延迟 P95 (ms)",
    "hold_turns": "仅校验门控的轮次",
}

_RAGAS_LABELS: dict[str, str] = {
    "faithfulness": "Faithfulness（回复是否有据可依）",
    "answer_relevancy": "Answer Relevancy（是否答到点上）",
    "context_precision": "Context Precision（放行内容是否精准）",
    "context_recall": "Context Recall（是否覆盖到参考答案）",
    "answer_correctness": "Answer Correctness（与参考答案的吻合度）",
}


def _run_id(run: EvalRun) -> str:
    stamp = run.started_at.replace(":", "").replace("-", "").replace("+", "_") or datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{run.mode}-seed{run.seed}"


def build_payload(
    run: EvalRun,
    deterministic: MetricOutcome,
    ragas: Optional[MetricOutcome] = None,
    *,
    extras: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """组装报告载荷。

    这里显式挑选字段，而不是直接 dump run.__dict__——run 里有 truth_anchors 这类
    内部真相素材，必须物理排除在载荷之外。
    """
    ragas = ragas or MetricOutcome()
    failed = [
        {
            "case_id": turn.case_id,
            "turn_index": turn.turn_index,
            "expect": list(turn.expect),
            "expect_stage": turn.expect_stage,
            "revealed_item": turn.revealed_item,
            "revealed_stage": turn.revealed_stage,
            "frontier_stage": turn.frontier_stage,
            "release_ok": turn.release_ok,
            "stage_ok": turn.stage_ok,
            "question": turn.question,
        }
        for turn in run.samples
        if (not turn.release_ok) or turn.stage_ok is False or not turn.gate_ok
    ]
    return {
        "meta": {
            "run_id": _run_id(run),
            "started_at": run.started_at,
            "mode": run.mode,
            "seed": run.seed,
            "duration_ms": round(run.duration_ms, 1),
            "game": {
                "environment": run.game.environment,
                "max_characters": run.game.max_characters,
            },
            "fingerprint": run.fingerprint,
        },
        "metrics": {
            "deterministic": deterministic.values,
            "ragas": ragas.values,
        },
        "ragas_per_sample": ragas.per_sample,
        "notes": list(run.notes) + list(deterministic.notes) + list(ragas.notes),
        "errors": list(deterministic.errors) + list(ragas.errors),
        "invalid_cases": list(run.invalid_cases),
        "failed_turns": failed,
        "extras": extras or {},
    }


def sample_records(run: EvalRun) -> list[dict[str, Any]]:
    """逐轮样本记录（只写计数，不写命中片段）。"""
    return [
        {
            "case_id": turn.case_id,
            "case_kind": turn.case_kind,
            "character": turn.character,
            "scope": turn.scope,
            "turn_index": turn.turn_index,
            "question": turn.question,
            "response": turn.response,
            "retrieved_contexts": list(turn.retrieved_contexts),
            "reference": turn.reference,
            "expect": list(turn.expect),
            "expect_stage": turn.expect_stage,
            "revealed_item": turn.revealed_item,
            "revealed_stage": turn.revealed_stage,
            "frontier_stage": turn.frontier_stage,
            "release_ok": turn.release_ok,
            "stage_ok": turn.stage_ok,
            "gate_ok": turn.gate_ok,
            "guard_clean": turn.guard_clean,
            "guard_sources": list(turn.guard_sources),
            "premature_disclosure_hits": len(turn.premature_item_hits),
            "truth_anchor_hits": len(turn.top_anchor_hits),
            "latency_ms": round(turn.latency_ms, 2),
        }
        for turn in run.samples
    ]


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(cell) for cell in row) + " |")
    return lines


def render_markdown(payload: dict[str, Any], *, redactions: int = 0) -> str:
    meta = payload["meta"]
    det = payload["metrics"]["deterministic"]
    rag = payload["metrics"]["ragas"]
    lines: list[str] = []
    lines.append("# Ragas 离线评估报告")
    lines.append("")
    lines.append(
        "本报告由 `python -m evaluation.run_eval` 生成：**评估在离线批处理里跑，游戏运行时绝不调用 Ragas**"
        "（Ragas 打分要额外调一次大模型，延迟与成本都不适合实时交互）。"
    )
    lines.append("")
    lines.append("## 运行信息")
    lines.append("")
    lines.extend(
        _table(
            ["项", "值"],
            [
                ["run_id", meta["run_id"]],
                ["时间", meta["started_at"]],
                ["模式", meta["mode"]],
                ["随机种子", meta["seed"]],
                ["耗时 (ms)", meta["duration_ms"]],
                ["场景", meta["game"]["environment"]],
                ["角色", "、".join(meta["fingerprint"].get("characters") or [])],
                ["揭示项总数", meta["fingerprint"].get("oracle_items")],
                ["各阶段揭示项", meta["fingerprint"].get("oracle_items_per_stage")],
                ["骨架数", meta["fingerprint"].get("skeletons")],
                ["落盘脱敏次数", redactions],
            ],
        )
    )
    lines.append("")
    lines.append("## 一、确定性指标（不依赖任何模型）")
    lines.append("")
    rows = [[_DETERMINISTIC_LABELS.get(key, key), det.get(key)] for key in _DETERMINISTIC_LABELS]
    rows.append(["场景分布（阶段0/1/2/未放行）", det.get("stage_distribution")])
    rows.append(["LeakGuard 命中来源", det.get("guard_finding_sources")])
    lines.extend(_table(["指标", "值"], rows))
    lines.append("")
    lines.append("## 二、Ragas 语义指标")
    lines.append("")
    if any(value is not None for value in rag.values()):
        rows = []
        for key, value in rag.items():
            if key.endswith(".n"):
                continue
            metric = key.split(".")[-1]
            family = key.split(".")[1] if key.count(".") >= 2 else "-"
            label = _RAGAS_LABELS.get(metric, metric)
            rows.append([f"{family} / {label}", value, rag.get(f"{key}.n")])
        lines.extend(_table(["指标", "均值", "样本数"], rows))
    else:
        lines.append("本次未运行 Ragas（原因见下方说明）。要跑语义指标：")
        lines.append("")
        lines.append("```bash")
        lines.append("cd backend")
        lines.append("venv\\Scripts\\python.exe -m pip install -r requirements-eval.txt")
        lines.append("venv\\Scripts\\python.exe -m evaluation.run_eval --mode llm --ragas reference")
        lines.append("```")
    lines.append("")
    lines.append("## 三、分类型明细")
    lines.append("")
    per_kind = det.get("per_kind") or {}
    if per_kind:
        lines.extend(
            _table(
                ["类型", "轮次", "放行", "LeakGuard 洁净", "阶段不符"],
                [
                    [kind, bucket["turns"], bucket["released"], bucket["guard_clean"], bucket["stage_mismatch"]]
                    for kind, bucket in sorted(per_kind.items())
                ],
            )
        )
    lines.append("")
    lines.append("## 四、阶梯贯通深度（decisive 用例走到第几档）")
    lines.append("")
    ladder = det.get("ladder_depth") or {}
    if ladder:
        lines.extend(_table(["用例", "最深层级"], [[case, depth] for case, depth in sorted(ladder.items())]))
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("## 五、未按预期通过的轮次")
    lines.append("")
    failed = payload["failed_turns"]
    if failed:
        lines.extend(
            _table(
                ["用例", "轮次", "期望", "期望阶段", "实际", "实际阶段", "门控前沿"],
                [
                    [
                        item["case_id"],
                        item["turn_index"],
                        item["expect"],
                        item["expect_stage"],
                        item["revealed_item"] or "未放行",
                        item["revealed_stage"],
                        item["frontier_stage"],
                    ]
                    for item in failed
                ],
            )
        )
    else:
        lines.append("（无：所有断言轮次都符合预期）")
    lines.append("")
    if payload["invalid_cases"]:
        lines.append("### 失效用例")
        lines.append("")
        lines.extend(f"- {item}" for item in payload["invalid_cases"])
        lines.append("")
    if payload["errors"]:
        lines.append("### 指标计算错误")
        lines.append("")
        lines.extend(f"- {item}" for item in payload["errors"][:30])
        lines.append("")
    if payload["notes"]:
        lines.append("### 说明")
        lines.append("")
        lines.extend(f"- {item}" for item in payload["notes"])
        lines.append("")
    lines.append("## 边界声明")
    lines.append("")
    lines.append("- 本报告只包含玩家可见内容与统计量：真凶身份、`murder_process`、骨架 secrets / private_facts 一律不写入。")
    lines.append("- 报告里的参考答案来自被测剧本的公开卷宗，不是内部真相。")
    lines.append("- 评估链路（`backend/evaluation/`）不被游戏代码导入，也不会出现在 WebSocket 动作路径上。")
    lines.append("")
    return "\n".join(lines)


def write_report(
    run: EvalRun,
    payload: dict[str, Any],
    *,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    write_samples: bool = True,
) -> dict[str, Path]:
    """写盘：先脱敏再落盘；返回各产物路径。"""
    anchors = list(run.truth_anchors)
    safe_payload, payload_redactions = scan_and_redact(payload, anchors)
    records, record_redactions = scan_and_redact(sample_records(run), anchors)
    total_redactions = int(payload_redactions) + int(record_redactions)
    safe_payload["redactions"] = total_redactions

    out_dir = Path(output_dir) / safe_payload["meta"]["run_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    report_json = out_dir / "report.json"
    report_json.write_text(json.dumps(safe_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["report_json"] = report_json

    report_md = out_dir / "report.md"
    report_md.write_text(render_markdown(safe_payload, redactions=total_redactions), encoding="utf-8")
    paths["report_md"] = report_md

    if write_samples:
        samples_path = out_dir / "samples.jsonl"
        with samples_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        paths["samples"] = samples_path
    return paths


__all__ = [
    "DEFAULT_OUTPUT_DIR",
    "build_payload",
    "render_markdown",
    "sample_records",
    "write_report",
]
