# tests/test_evaluation.py
# 离线评估子系统的单测（全部离线运行，不需要 key、不需要 ragas 真身）。
#
# 三个关注点：
#   1. 评估本身可信：用例自检、跑批样本结构、门控不变式、阶梯推进；
#   2. 落盘不泄密：报告脱敏、载荷里不出现真相锚点；
#   3. 运行时隔离：游戏代码不导入 evaluation / ragas；evaluation 包不导入 ragas。

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("AI_MURDER_OFFLINE", "1")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evaluation.dataset import (  # noqa: E402
    ANY_ITEM,
    EvalCase,
    EvalTurn,
    load_cases,
    select_cases,
    validate_cases,
)
from evaluation.harness import EvalUnavailable, run_evaluation  # noqa: E402
from evaluation.leakscan import anchors_hit, scan_and_redact, text_anchors  # noqa: E402
from evaluation.metrics import deterministic_metrics  # noqa: E402
from evaluation.providers import JudgeStack  # noqa: E402
from evaluation.report import build_payload, render_markdown, sample_records, write_report  # noqa: E402


def _small_run(limit: int = 0):
    game, cases = load_cases()
    picked = select_cases(cases, None, limit)
    return game, picked, run_evaluation(game, picked, mode="offline")


class TestCaseData(unittest.TestCase):
    def test_shipped_cases_load_and_self_check(self):
        game, cases = load_cases()
        self.assertTrue(cases, "用例集不能为空")
        self.assertEqual(len({case.id for case in cases}), len(cases), "用例 id 不能重复")
        self.assertTrue(game.environment)

    def test_self_check_flags_bad_item_id_and_missing_reference(self):
        bad_id = EvalCase(
            id="bad-id",
            kind="alibi",
            character="沈慕白",
            scope="both",
            turns=(EvalTurn(question="问一句", expect=("oracle:不存在的角色:9",)),),
        )
        missing_ref = EvalCase(
            id="missing-ref",
            kind="alibi",
            character="沈慕白",
            scope="both",
            turns=(EvalTurn(question="问一句", expect=(ANY_ITEM,)),),
        )
        problems = validate_cases([bad_id, missing_ref], {"oracle:沈慕白:0"})
        joined = " | ".join(problems)
        self.assertIn("揭示项不存在", joined)
        self.assertIn("缺少参考答案", joined)

    def test_select_cases_rejects_unknown_id(self):
        _game, cases = load_cases()
        with self.assertRaises(ValueError):
            select_cases(cases, ["不存在的用例"], 0)


class TestHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 注意：别把结果挂到 cls.run —— 那是 unittest.TestCase.run 的名字。
        cls.game, cls.cases, cls.eval_run = _small_run()

    def test_offline_run_produces_samples(self):
        self.assertTrue(self.eval_run.samples)
        self.assertEqual(self.eval_run.invalid_cases, [])

    def test_offline_mode_switches_model_off(self):
        """离线跑批期间模型必须是关掉的（这条自证自足，不依赖别的用例留下的环境）。"""
        from config import llm_available

        game, cases = load_cases()
        self.addCleanup(lambda: os.environ.__setitem__("AI_MURDER_OFFLINE", "1"))
        run_evaluation(game, select_cases(cases, None, 1), mode="offline")
        self.assertEqual(os.environ.get("AI_MURDER_OFFLINE"), "1")
        self.assertFalse(llm_available(), "离线跑批期间模型必须是关掉的")

    def test_first_turn_never_exceeds_stage_zero(self):
        """门控契约：每个用例的第一轮只可能放行行踪档。"""
        for sample in self.eval_run.samples:
            if sample.turn_index != 0 or sample.revealed_stage is None:
                continue
            self.assertEqual(sample.revealed_stage, 0, f"{sample.case_id} 首轮越级放行")

    def test_gate_invariant_holds(self):
        self.assertTrue(all(sample.gate_ok for sample in self.eval_run.samples), "不允许越级放行")

    def test_decisive_ladder_reaches_deep_stage(self):
        ladder = deterministic_metrics(self.eval_run).values["ladder_depth"]
        self.assertEqual(ladder.get("smb-ladder-depth"), 2, "六轮应当走到决定性档")

    def test_reply_contexts_are_player_visible_only(self):
        """retrieved_contexts 只应包含公开案情与已放行揭示，不含内部真相。"""
        for sample in self.eval_run.samples:
            for context in sample.retrieved_contexts:
                self.assertNotIn("乌头碱粉末", context)

    def test_llm_mode_requires_model(self):
        game, _cases = load_cases()
        from config import llm_available

        # 先还原到“真去连模型”的状态再判断，避免被别的用例设置离线标志干扰。
        os.environ.pop("AI_MURDER_OFFLINE", None)
        self.addCleanup(lambda: os.environ.__setitem__("AI_MURDER_OFFLINE", "1"))
        if llm_available():
            self.skipTest("本机配了可用的模型，--mode llm 能正常起来，跳过缺模型分支")
        with self.assertRaises(EvalUnavailable):
            run_evaluation(game, [], mode="llm")
        self.assertFalse(llm_available(), "起不来时必须把离线状态还原回去")


class TestDeterministicMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metrics = deterministic_metrics(_small_run()[2])

    def test_expected_keys_present(self):
        for key in (
            "release_precision",
            "release_recall",
            "gate_pass_rate",
            "guard_clean_rate",
            "truth_leak_rate",
            "premature_disclosure_rate",
            "stage_distribution",
            "per_kind",
        ):
            self.assertIn(key, self.metrics.values)

    def test_no_truth_leak_and_no_premature_disclosure(self):
        self.assertEqual(self.metrics.values["truth_leak_rate"], 0.0)
        self.assertEqual(self.metrics.values["premature_disclosure_rate"], 0.0)

    def test_baseline_precision_gap_is_the_known_one(self):
        """基线：目前只有 safety-off-topic-weather 这一条误放行（见 evaluation/README.md）。

        哪天把这个精度缺口修好了，这里会失败——那是好事，同步更新基线数字即可。
        """
        self.assertEqual(self.metrics.values["over_release_turns"], 1)
        self.assertEqual(self.metrics.values["under_release_turns"], 0)
        self.assertEqual(self.metrics.values["gate_pass_rate"], 1.0)

    def test_every_asserted_release_happened(self):
        self.assertEqual(self.metrics.values["release_recall"], 1.0)


class TestLeakScanAndReport(unittest.TestCase):
    def test_anchor_hit_needs_long_common_run(self):
        anchor = text_anchors(["十点五十分他从花园侧门潜回书房收走酒杯擦掉指纹"])
        self.assertTrue(anchors_hit("他说十点五十分他从花园侧门潜回书房收走酒杯擦掉指纹", anchor))
        self.assertFalse(anchors_hit("他说他当时在花园抽烟", anchor))

    def test_scan_and_redact_walks_nested_payload(self):
        anchor = text_anchors(["九点五十分他把乌头碱粉末倒进她杯中的红酒里"])
        payload = {"a": ["干净的话", "九点五十分他把乌头碱粉末倒进她杯中的红酒里"], "b": {"c": 1}}
        cleaned, count = scan_and_redact(payload, anchor)
        self.assertEqual(count, 1)
        self.assertEqual(cleaned["a"][0], "干净的话")
        self.assertNotIn("乌头碱", json.dumps(cleaned, ensure_ascii=False))

    def test_payload_never_carries_truth_anchors(self):
        game, cases, run = _small_run()
        payload = build_payload(run, deterministic_metrics(run))
        self.assertNotIn("truth_anchors", json.dumps(payload, ensure_ascii=False))
        self.assertTrue(run.truth_anchors, "跑批应保留真相锚点用于落盘扫描")

    def test_report_redacts_planted_truth_before_writing(self):
        game, cases, run = _small_run()
        payload = build_payload(run, deterministic_metrics(run))
        planted = "九点五十分他在书房与她说笑，随后把乌头碱粉末倒进杯中，又擦掉杯沿指纹。"
        payload["extras"]["planted"] = planted
        run.truth_anchors = tuple(text_anchors([planted]))

        out_dir = BACKEND_DIR / "tests" / "_tmp_eval_report"
        paths = write_report(run, payload, output_dir=out_dir)
        try:
            written_md = paths["report_md"].read_text(encoding="utf-8")
            written_json = paths["report_json"].read_text(encoding="utf-8")
            self.assertNotIn("乌头碱", written_md)
            self.assertNotIn("乌头碱", written_json)
            self.assertIn("落盘脱敏次数", written_md)
            self.assertIn("## 一、确定性指标", written_md)
        finally:
            for path in sorted(paths.values()):
                path.unlink(missing_ok=True)
            run_dir = paths["report_md"].parent
            try:
                run_dir.rmdir()
            except OSError:
                pass
            try:
                out_dir.rmdir()
            except OSError:
                pass

    def test_markdown_renders_without_ragas(self):
        game, cases, run = _small_run()
        text = render_markdown(build_payload(run, deterministic_metrics(run)))
        self.assertIn("游戏运行时绝不调用 Ragas", text)
        self.assertIn("边界声明", text)

    def test_sample_records_omit_anchor_text(self):
        game, cases, run = _small_run()
        blob = json.dumps(sample_records(run), ensure_ascii=False)
        self.assertIn("truth_anchor_hits", blob)
        self.assertNotIn("top_anchor_hits", blob)


class TestRuntimeIsolation(unittest.TestCase):
    """硬约束：游玩链路不碰评估、不碰 ragas。"""

    def test_game_sources_do_not_reference_evaluation_or_ragas(self):
        offenders = []
        targets = sorted(BACKEND_DIR.glob("*.py")) + sorted((BACKEND_DIR / "role_skeleton").glob("*.py"))
        for path in targets:
            source = path.read_text(encoding="utf-8").lower()
            if "ragas" in source or "evaluation" in source:
                offenders.append(path.name)
        self.assertEqual(offenders, [], "游戏侧代码不得引用评估子系统或 ragas")

    def test_importing_server_pulls_no_ragas(self):
        code = (
            "import sys, main;"
            "assert 'ragas' not in sys.modules, 'ragas 被拖进运行时';"
            "assert 'evaluation' not in sys.modules, 'evaluation 被拖进运行时';"
            "print('ok')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_evaluation_package_imports_without_ragas(self):
        code = (
            "import sys;"
            "import evaluation, evaluation.harness, evaluation.metrics, evaluation.report, evaluation.providers;"
            "assert 'ragas' not in sys.modules, '导入评估包时不应加载 ragas';"
            "print('ok')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)


class _FakeSingleTurnSample:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeModernMetric:
    """模拟 ragas 0.2+ 的类式指标 + async single_turn_ascore。"""

    def __init__(self, llm=None, embeddings=None):
        self.llm = llm
        self.embeddings = embeddings

    async def single_turn_ascore(self, sample):
        return 0.5 if getattr(sample, "reference", None) else 0.25


class _FakeLegacyMetric:
    """模拟 0.1 的小写单例 + 同步 single_turn_score，且打分直接抛错。"""

    def single_turn_score(self, sample):
        raise RuntimeError("legacy metric boom")


class TestRagasAdapter(unittest.TestCase):
    """用假 ragas 模块验证适配层：版本探测、逐样本打分、失败记录。

    本机没装 ragas 也能跑，保证真正装上 ragas 时装配行为是对的。
    """

    def setUp(self):
        self._saved = {
            name: sys.modules.get(name)
            for name in (
                "ragas",
                "ragas.metrics",
                "ragas.metrics.collections",
                "ragas.llms",
                "ragas.embeddings",
            )
        }
        ragas = types.ModuleType("ragas")
        ragas.SingleTurnSample = _FakeSingleTurnSample
        metrics_module = types.ModuleType("ragas.metrics")
        metrics_module.Faithfulness = _FakeModernMetric
        metrics_module.AnswerRelevancy = _FakeModernMetric
        metrics_module.context_recall = _FakeLegacyMetric()
        llms_module = types.ModuleType("ragas.llms")
        llms_module.LangchainLLMWrapper = lambda inner: ("llm-wrapper", inner)
        embeddings_module = types.ModuleType("ragas.embeddings")
        embeddings_module.LangchainEmbeddingsWrapper = lambda inner: ("emb-wrapper", inner)
        sys.modules.update(
            {
                "ragas": ragas,
                "ragas.metrics": metrics_module,
                "ragas.llms": llms_module,
                "ragas.embeddings": embeddings_module,
            }
        )
        sys.modules.pop("ragas.metrics.collections", None)

    def tearDown(self):
        for name, module in self._saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_judge_stack_without_model_reports_clearly(self):
        from config import llm_available
        from evaluation.providers import build_judge_stack

        if llm_available():
            stack = build_judge_stack(mode="deterministic")
            self.assertIsInstance(stack, JudgeStack)
            self.assertIn("deterministic", stack.embeddings_label)
        else:
            with self.assertRaises(EvalUnavailable):
                build_judge_stack()

    def test_metrics_score_samples_and_record_failures(self):
        from evaluation.metrics import ragas_metrics

        game, cases, run = _small_run(limit=3)
        judge = JudgeStack(llm="fake-llm", embeddings="fake-emb", llm_label="t", embeddings_label="t")
        outcome = ragas_metrics(run, families=("reference",), judge=judge)

        self.assertEqual(outcome.values["ragas.reference.faithfulness"], 0.5)
        self.assertEqual(outcome.values["ragas.reference.faithfulness.n"], len(run.reference_samples))
        self.assertIsNone(outcome.values["ragas.reference.context_recall"])
        self.assertTrue(any("legacy metric boom" in item for item in outcome.errors))
        self.assertTrue(outcome.per_sample)
        self.assertEqual(outcome.per_sample[0]["metric_impl"], "Faithfulness")

    def test_reference_free_family_skips_reference_requirement(self):
        from evaluation.metrics import ragas_metrics

        game, cases, run = _small_run()
        judge = JudgeStack(llm="fake-llm", embeddings="fake-emb", llm_label="t", embeddings_label="t")
        outcome = ragas_metrics(run, families=("reference_free",), judge=judge)
        self.assertEqual(outcome.values["ragas.reference_free.faithfulness.n"], len(run.samples))
        self.assertEqual(outcome.values["ragas.reference_free.faithfulness"], 0.25)

    def test_missing_metric_is_reported_not_silently_skipped(self):
        from evaluation.metrics import ragas_metrics

        game, cases, run = _small_run(limit=1)
        judge = JudgeStack(llm="fake-llm", embeddings="fake-emb", llm_label="t", embeddings_label="t")
        outcome = ragas_metrics(run, families=("reference",), judge=judge)
        self.assertTrue(
            [item for item in outcome.errors if "找不到该指标" in item],
            "假 ragas 里没有 context_precision，必须显式报出来",
        )

    def test_deterministic_embeddings_are_flagged_in_notes(self):
        """假向量下 embedding 类指标不可信，必须在报告里说出来，不能让人当成论文数字。"""
        from evaluation.metrics import ragas_metrics

        game, cases, run = _small_run(limit=1)
        judge = JudgeStack(
            llm="fake-llm",
            embeddings="fake-emb",
            llm_label="deepseek:deepseek-chat",
            embeddings_label="deterministic-fake-384d",
        )
        outcome = ragas_metrics(run, families=("reference",), judge=judge)
        self.assertTrue(
            any("answer_relevancy" in item and "没有语义意义" in item for item in outcome.notes),
            f"缺确定性向量的口径提示：{outcome.notes}",
        )


class _FakeTunableMetric:
    """模拟 ragas 0.3.9 的 AnswerRelevancy / AnswerCorrectness 两个坑。"""

    def __init__(self, llm=None, embeddings=None):
        self.llm = llm
        self.embeddings = embeddings
        self.strictness = 3
        self.init_calls = 0
        self.answer_similarity = None

    def init(self, run_config):
        self.init_calls += 1
        self.answer_similarity = ("similarity", self.embeddings)

    async def single_turn_ascore(self, sample):
        assert self.answer_similarity is not None, "AnswerSimilarity must be set"
        return 0.5 if self.strictness == 1 else 0.0


class TestJudgeTuning(unittest.TestCase):
    """逐样本打分下必须做的两处适配（都是真跑 ragas + DeepSeek 才暴露出来的）。"""

    def test_strictness_is_pinned_to_one_and_init_is_called(self):
        from evaluation.metrics import _instantiate, _score_single

        judge = JudgeStack(llm="fake-llm", embeddings="fake-emb", llm_label="t", embeddings_label="t")
        notes: list[str] = []
        metric = _instantiate(_FakeTunableMetric, judge, notes)

        self.assertEqual(metric.strictness, 1, "DeepSeek 只支持 n=1，strictness 必须压到 1")
        self.assertEqual(metric.init_calls, 1, "逐样本打分不会触发 init()，适配层要手动补一次")
        self.assertEqual(_score_single(metric, _FakeSingleTurnSample()), 0.5)
        self.assertEqual(len(notes), 2, notes)

    def test_instantiate_still_works_without_notes(self):
        from evaluation.metrics import _instantiate

        judge = JudgeStack(llm="fake-llm", embeddings="fake-emb", llm_label="t", embeddings_label="t")
        metric = _instantiate(_FakeTunableMetric, judge)
        self.assertEqual(metric.strictness, 1)
        self.assertEqual(metric.init_calls, 1)

    def test_untunable_metric_is_left_alone(self):
        from evaluation.metrics import _instantiate

        judge = JudgeStack(llm="fake-llm", embeddings="fake-emb", llm_label="t", embeddings_label="t")
        notes: list[str] = []
        metric = _instantiate(_FakeModernMetric, judge, notes)
        self.assertEqual(notes, [], "没有 strictness / init 的指标不应被记一笔")
        self.assertIsInstance(metric, _FakeModernMetric)


class TestAsyncHttpClient(unittest.TestCase):
    """Ragas 走异步打分，异步 client 必须和 config 的同步 client 同口径（trust_env=False）。"""

    def test_async_client_disables_trust_env(self):
        from evaluation.providers import build_async_http_client

        client = build_async_http_client()
        try:
            self.assertFalse(
                client.trust_env,
                "异步 client 必须 trust_env=False，否则会读到 SSL_CERT_FILE 之类的环境变量",
            )
        finally:
            import asyncio

            asyncio.run(client.aclose())

    def test_judge_model_keeps_sync_client_and_adds_async_one(self):
        try:
            from langchain_openai import ChatOpenAI
        except Exception:  # pragma: no cover - 缺依赖时跳过
            self.skipTest("没有 langchain_openai")
        from evaluation.providers import _judge_model

        base = ChatOpenAI(model="deepseek-chat", api_key="dummy-key", base_url="http://127.0.0.1:1/v1")
        model, async_client = _judge_model(base)
        try:
            self.assertIs(model.http_async_client, async_client)
            self.assertFalse(async_client.trust_env)
            self.assertIs(model.http_client, base.http_client, "同步 client 应沿用原模型那条")
            self.assertEqual(model.model_name, base.model_name)
        finally:
            import asyncio

            asyncio.run(async_client.aclose())

    def test_judge_stack_close_is_idempotent_without_client(self):
        judge = JudgeStack(llm="l", embeddings="e", llm_label="t", embeddings_label="t")
        judge.close()
        judge.close()


if __name__ == "__main__":
    unittest.main()
