# evaluation/run_eval.py
# 离线评估 CLI。
#
#   cd backend
#   venv\Scripts\python.exe -m evaluation.run_eval                        # 确定性指标（离线、免费、快）
#   venv\Scripts\python.exe -m evaluation.run_eval --ragas reference      # 追加 Ragas 语义指标（需要 key）
#
# 全部参数都在 evaluation/README.md 里有说明。

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from .dataset import CASES_PATH, load_cases, select_cases, validate_cases
from .harness import EvalUnavailable, run_evaluation
from .metrics import FAMILIES, deterministic_metrics, ragas_metrics
from .providers import build_judge_stack
from .report import DEFAULT_OUTPUT_DIR, build_payload, render_markdown, write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.run_eval",
        description="AI 悬疑推理游戏：离线批量评估（Ragas + 确定性门控指标）",
    )
    parser.add_argument("--cases", default=str(CASES_PATH), help="用例文件路径（默认 evaluation/cases.json）")
    parser.add_argument("--only", default="", help="只跑指定用例 id，逗号分隔")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 个用例（0 = 全部）")
    parser.add_argument(
        "--mode",
        choices=("offline", "llm"),
        default="offline",
        help="offline：NPC 回复走确定性兜底（默认，可复现、不花钱）；llm：走真实模型",
    )
    parser.add_argument("--seed", type=int, default=20240924, help="随机种子（剧本洗牌与兜底话术）")
    parser.add_argument(
        "--ragas",
        default="",
        help=(
            "要跑的 Ragas 指标族，逗号分隔：reference（有参考答案，完整指标族）/ "
            "reference_free（全部用例，只跑不需要参考答案的指标）。留空 = 不跑 Ragas"
        ),
    )
    parser.add_argument("--max-ragas-samples", type=int, default=0, help="每个指标最多打分多少个样本（0 = 全部）")
    parser.add_argument("--ragas-sleep", type=float, default=0.0, help="样本之间的间隔秒数（限速用）")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR), help="产物目录")
    parser.add_argument("--no-write", action="store_true", help="只打印，不落盘")
    parser.add_argument("--quiet", action="store_true", help="只打印一句话摘要")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.perf_counter()

    try:
        game, cases = load_cases(args.cases)
    except (OSError, ValueError) as exc:
        print(f"[评估] 用例文件读取失败：{exc}", file=sys.stderr)
        return 2

    only = [item.strip() for item in str(args.only or "").split(",") if item.strip()]
    try:
        cases = select_cases(cases, only or None, int(args.limit or 0))
    except ValueError as exc:
        print(f"[评估] {exc}", file=sys.stderr)
        return 2
    if not cases:
        print("[评估] 没有选中任何用例。", file=sys.stderr)
        return 2

    families = [item.strip() for item in str(args.ragas or "").split(",") if item.strip()]
    unknown = [item for item in families if item not in FAMILIES]
    if unknown:
        print(f"[评估] --ragas 不支持这些取值：{'、'.join(unknown)}（可选：{'/'.join(FAMILIES)}）", file=sys.stderr)
        return 2
    if families and args.mode != "llm":
        print(
            "[评估] Ragas 需要判分模型，请配合 --mode llm 使用（离线模式会把模型整体关掉）。",
            file=sys.stderr,
        )
        return 2

    try:
        run = run_evaluation(game, cases, mode=args.mode, seed=int(args.seed))
    except EvalUnavailable as exc:
        print(f"[评估] {exc}", file=sys.stderr)
        return 2

    deterministic = deterministic_metrics(run)
    ragas = None
    if families:
        try:
            judge = build_judge_stack()
            try:
                ragas = ragas_metrics(
                    run,
                    families=families,
                    judge=judge,
                    max_samples=int(args.max_ragas_samples or 0),
                    sleep_s=float(args.ragas_sleep or 0.0),
                )
            finally:
                judge.close()
        except EvalUnavailable as exc:
            print(f"[评估] Ragas 未运行：{exc}", file=sys.stderr)
            return 2

    payload = build_payload(
        run,
        deterministic,
        ragas,
        extras={"cli": {"families": families, "max_ragas_samples": args.max_ragas_samples}},
    )
    payload["extras"]["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)

    # 用例自检失败（写死的揭示项对不上 / scope=both 缺参考答案）视为数据问题，退出码 1。
    problems = validate_cases(cases, {})
    if problems:
        payload["invalid_cases"].extend(problems)

    paths: dict[str, Path] = {}
    if args.no_write:
        anchors = list(run.truth_anchors)
        from .leakscan import scan_and_redact

        safe_payload, redactions = scan_and_redact(payload, anchors)
        payload = safe_payload
        payload["redactions"] = redactions
    else:
        paths = write_report(run, payload, output_dir=args.output)

    if args.quiet:
        det = payload["metrics"]["deterministic"]
        print(
            f"[评估] 完成：{det.get('turns')} 轮 / {det.get('cases')} 用例 "
            f"| 放行精确率={det.get('release_precision')} 召回率={det.get('release_recall')} "
            f"| 门控通过率={det.get('gate_pass_rate')} | LeakGuard 洁净率={det.get('guard_clean_rate')}"
        )
    else:
        print(render_markdown(payload, redactions=int(payload.get("redactions") or 0)))

    if paths:
        print("[评估] 产物：")
        for name, path in paths.items():
            print(f"  - {name}: {path}")
    return 1 if payload["invalid_cases"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
