import json
import os
import unittest

os.environ.setdefault("AI_MURDER_OFFLINE", "1")

from coach import candidate_questions, clean_text, confirm_question, find_time
from deterministic_game import build_deterministic_game
from judge import _parse_llm_reasoning, reason_heuristic, score_game
from oracle import (
    OracleItem,
    build_oracle_items,
    expose_item,
    oracle_choose,
    proximity_signal,
    revealable_items,
)
from role_skeleton.guard import LeakGuard
from role_skeleton.runner import constrained_answer
from role_skeleton.schema import KnowledgeBoundary, RoleSkeleton, Secret, SkeletonPolicy


def _suspect_items(oracle_items, name):
    return [item for item in oracle_items if item.owner == name]


class TestOracleStage(unittest.TestCase):
    """oracle 分阶段放行：决定性细节必须先解锁前面的行踪/矛盾档。"""

    def setUp(self):
        self.state = build_deterministic_game("测试庄园", 5)
        self.story = self.state["story_details"]
        self.chars = self.state["characters"]
        self.items = build_oracle_items(self.story, self.chars)

    def test_initial_gate_only_opens_shallower_stage(self):
        for name in {"沈慕白", "苏棠", "陆时谦", "陈妈"}:
            own = _suspect_items(self.items, name)
            if not own:
                continue
            revealable = revealable_items(own)
            for item in revealable:
                self.assertEqual(item.stage, 0, f"{name} 开局只应放出阶段0")

    def test_decisive_unlock_requires_earlier_stages(self):
        own = _suspect_items(self.items, "沈慕白")
        if len(own) < 3:
            self.skipTest("该局此嫌疑人揭示项不足")
        for item in own:
            if item.stage == 2:
                decisive = item
                break
        else:
            self.skipTest("没有决定性揭示项")
        self.assertNotIn(decisive, revealable_items(own))
        for item in own:
            if item.stage < 2:
                expose_item(item)
        self.assertIn(decisive, revealable_items(own))

    def test_relevant_question_unlocks(self):
        own = _suspect_items(self.items, "沈慕白")
        revealable = revealable_items(own)
        hit = None
        for question in (
            "那晚九点五十分前后你人在哪儿？有人看见过你吗？",
            "有人说你十点后在走廊尽头碰见陈妈——你当时在做什么？",
        ):
            hit = oracle_choose(question, revealable, self.story, self.chars)
            if hit is not None:
                break
        self.assertIsNotNone(hit, "问到时间/地点应当能命中一条行踪揭示")

    def test_proximity_signal_is_soft(self):
        own = _suspect_items(self.items, "沈慕白")
        revealable = revealable_items(own)
        level, _item = proximity_signal("听说你那晚心情不太好？", revealable, self.story, self.chars)
        self.assertIn(level, (0, 1))


class TestCoachQuestions(unittest.TestCase):
    """coach：候选问法至少给出确认问，且去重。"""

    def test_candidates_nonempty_and_no_dup(self):
        state = build_deterministic_game("测试庄园", 5)
        story = state["story_details"]
        suspect = next(c for c in state["characters"] if c.role != "Victim")
        items = build_oracle_items(story, state["characters"])
        own = [item for item in items if item.owner == suspect.name]
        questions = candidate_questions(
            character=suspect,
            story=story,
            npc_last="那晚我一直待在西翼书房里打电话。",
            player_last="你听见书房那边有动静吗？",
            locked=own,
            llm_questions=[],
        )
        self.assertTrue(questions)
        keys = [clean_text(q) for q in questions]
        self.assertEqual(len(keys), len(set(keys)), "候选问法不应重复")

    def test_confirm_question_and_time(self):
        self.assertIsNotNone(find_time("晚上十点四十分前后我回房了"))
        self.assertTrue((confirm_question("陈妈说九点五十分她听见书房里有男人的说话声") or "").startswith("对了"))


class TestSkeletonGuard(unittest.TestCase):
    """骨架输出审查 + 分级重试（fake generator 验证闭环）。"""

    def _skeleton(self):
        return RoleSkeleton(
            agent_id="sk_test",
            display_name="测试角色",
            role_label="嫌疑人",
            public_profile="庄园管家",
            secrets=(Secret(title="真实身份", content="他其实一直在暗中转移信托资金"),),
            knowledge=KnowledgeBoundary(
                known=("当晚九点后在一楼厨房收拾",),
                unknown=("死者的遗嘱受益人是她自己改的",),
            ),
            policy=SkeletonPolicy(
                bottom_lines=("不得承认自己与信托账目有关",),
                forbidden_phrases=("转移信托资金",),
            ),
        )

    def test_guard_rejects_forbidden_text(self):
        skeleton = self._skeleton()
        audit = LeakGuard(skeleton).audit("其实我一直在转移信托资金，账目是我动的。")
        self.assertFalse(audit.clean)
        self.assertIn("forbidden_phrase", audit.sources)

    def test_constrained_answer_retries_to_clean(self):
        skeleton = self._skeleton()
        calls = {"n": 0}

        def fake_generate(_steering):
            calls["n"] += 1
            if calls["n"] == 1:
                return "没错，我一直在暗中转移信托资金，账也是我平的。"
            return "那天的事我不太想谈，你先别问了。"

        final_text, records = constrained_answer(skeleton, fake_generate, max_retry=2)
        self.assertTrue(records[-1].clean)
        self.assertGreater(calls["n"], 1)
        self.assertNotIn("信托资金确实是我转走的", final_text)


class TestJudgeScore(unittest.TestCase):
    """结算打分：确定性启发式 + 可注入 fake LLM。"""

    def test_heuristic_reasoning(self):
        state = build_deterministic_game("测试庄园", 5)
        reason = "他把乌头碱倒进红酒，遗嘱和信托账目都是他动的手脚。"
        score = reason_heuristic(reason, state["story_details"], "沈慕白")
        self.assertGreaterEqual(score, 40)

    def test_fake_llm_reasoning(self):
        def fake_llm(_prompt):
            return json.dumps(
                {
                    "score": 88,
                    "key_points_found": ["抓到账目矛盾"],
                    "key_points_missed": ["漏掉袖扣证据"],
                    "feedback": "主线推理成立",
                },
                ensure_ascii=False,
            )

        parsed = _parse_llm_reasoning(fake_llm(""))
        self.assertEqual(parsed.get("score"), 88)
        state = build_deterministic_game("测试庄园", 5)
        items = build_oracle_items(state["story_details"], state["characters"])
        breakdown = score_game(
            items,
            reason="律师用毒药杀人并动了账目。",
            guess_correct=True,
            guesses_left=2,
            llm_fn=fake_llm,
            story=state["story_details"],
            killer_name="沈慕白",
        )
        self.assertEqual(breakdown["reasoning"], 88)


if __name__ == "__main__":
    unittest.main()