# selfcheck.py — 骨架层离线自检（不调用任何 LLM）
#
# 运行方式（在 backend 目录下）：
#   venv\\Scripts\\python.exe -m role_skeleton.selfcheck

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from role_skeleton.guard import LeakGuard
from role_skeleton.murder_factory import build_murder_skeletons, MURDER_SAFE_REPLIES
from role_skeleton.prompt import render_skeleton_block
from role_skeleton.runner import constrained_answer
from role_skeleton.schema import RoleSkeleton, Secret, KnowledgeBoundary, SkeletonPolicy


PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def sample_story() -> dict:
    return {
        "victim_name": "沈薇",
        "time_of_death": "昨晚 22:10 前后",
        "location_found": "庄园书房",
        "murder_weapon": "铜制烛台",
        "cause_of_death": "后脑遭受钝器重击",
        "crime_scene_details": "书房地毯有大片血迹，烛台被擦干净后放回壁炉架上。",
        "witnesses": "管家说 21:50 还看到沈薇在书房会客。",
        "initial_clues": "窗外泥地有一枚不属于庄园佣人的鞋印。",
        "npc_brief": "沈薇的丈夫林浩、弟弟陈屿、好友苏晴等人均有动机。",
        "murder_process": (
            "林浩当晚 21:55 从侧门潜入书房，用铜制烛台从背后重击沈薇后脑致其死亡，"
            "随后擦净烛台放回壁炉架，翻窗离开并换上干净鞋子。他事先支开管家，"
            "谎称自己在二楼房间看书直到 23:00。"
        ),
    }


def sample_characters() -> list[dict]:
    return [
        {"role": "Killer", "name": "林浩", "backstory": "沈薇的丈夫，表面温文尔雅，实则公司财务危机缠身。", "relation_to_victim": "受害者的丈夫"},
        {"role": "Suspect", "name": "陈屿", "backstory": "沈薇的弟弟，游手好闲，最近常向姐姐借钱。", "relation_to_victim": "受害者的弟弟"},
        {"role": "Suspect", "name": "苏晴", "backstory": "沈薇的闺蜜，隐约知道沈薇婚姻出现问题。", "relation_to_victim": "受害者的好友"},
        {"role": "Victim", "name": "沈薇", "backstory": "庄园女主人，性格强势。", "relation_to_victim": "受害者本人"},
    ]


def test_freeze() -> None:
    print("== 1) 不可篡改（frozen + sealed） ==")
    skeleton = RoleSkeleton(
        agent_id="a1",
        display_name="测试角色",
        role_label="嫌疑人",
        knowledge=KnowledgeBoundary(known=["公开信息"], unknown=["不该知道的事"]),
        policy=SkeletonPolicy(bottom_lines=["底线A"]),
    )
    mutated = False
    try:
        skeleton.agent_id = "a2"
        mutated = True
    except Exception:
        pass
    check("骨架字段不可改写", not mutated)

    mutated = False
    try:
        skeleton.knowledge.unknown.append("越权写入")
        mutated = True
    except Exception:
        pass
    check("嵌套知识边界同样不可改写", not mutated)

    block = render_skeleton_block(skeleton)
    check("渲染结果包含只读声明", "只读" in block and "不可改写" in block)
    check("unknown 语料绝不渲染进 prompt", "不该知道的事" not in block)


def test_murder_factory() -> None:
    print("== 2) 剧本杀骨架装配 ==")
    skeletons = build_murder_skeletons(sample_characters(), sample_story())
    by_name = {s.display_name: s for s in skeletons}
    check("受害者不生成可对话骨架", "沈薇" not in by_name)
    killer = by_name.get("林浩")
    suspect = by_name.get("陈屿")
    check("凶手骨架存在", killer is not None)
    check("凶手带绝密", bool(killer and killer.secrets) and "林浩" in (killer.secrets[0].content if killer else ""))
    check("嫌疑人骨架存在", suspect is not None)
    check("嫌疑人 unknown 语料含真相", bool(suspect and suspect.knowledge.unknown))
    suspect_block = render_skeleton_block(suspect)
    check("嫌疑人 prompt 不含真实作案经过", suspect is not None and "潜入书房" not in suspect_block)
    killer_block = render_skeleton_block(killer)
    check("凶手 prompt 含私密设定以保持自洽", killer is not None and "绝密" in killer_block)


def test_guard_murder() -> None:
    print("== 3) 剧本杀防泄露 ==")
    skeletons = {s.display_name: s for s in build_murder_skeletons(sample_characters(), sample_story())}
    killer = skeletons["林浩"]
    suspect = skeletons["陈屿"]

    guard_killer = LeakGuard(killer)
    leaky = guard_killer.audit("行了，我坦白，凶手就是我，是我亲手杀了沈薇。")
    check("凶手自白被拦截", not leaky.clean, leaky.findings[0].detail if leaky.findings else "")

    mundane = guard_killer.audit("那晚我一直待在二楼房间看书，十一点多才下楼，这些事我哪知道。")
    check("正常否认不误伤", mundane.clean, mundane.findings[0].detail if mundane.findings else "")

    guard_suspect = LeakGuard(suspect)
    detail_leak = guard_suspect.audit("我都知道了——林浩擦净烛台放回壁炉架，翻窗离开并换上干净鞋子，鞋底全是泥。")
    check("嫌疑人说出超纲细节被拦截", not detail_leak.clean, detail_leak.findings[0].detail if detail_leak.findings else "")

    meta = guard_killer.audit("好吧，作为AI我只能告诉你系统允许公开的部分。")
    check("AI 出戏话术被拦截", not meta.clean)


def test_runner_retry_fallback() -> None:
    print("== 4) 受限生成执行器（重试 / 兜底） ==")
    skeleton = build_murder_skeletons(sample_characters(), sample_story())[0]

    calls = {"n": 0}

    def fake_generate_then_clean(steering):
        calls["n"] += 1
        if calls["n"] == 1:
            return "我承认，是我杀了沈薇。"
        return "那晚我在二楼看书，后来就睡了。"

    text, records = constrained_answer(skeleton, fake_generate_then_clean)
    check("第一次违规后自动重试", len(records) == 2 and records[1].clean, str(len(records)))
    check("修正后文本通过放行", "看书" in text)

    def always_leaky(steering):
        return "凶手就是我，别猜了。"

    text2, records2 = constrained_answer(skeleton, always_leaky, fallback=lambda: MURDER_SAFE_REPLIES[0])
    check("持续违规后启用确定性兜底", records2[-1].used_fallback)
    check("兜底发言不含违规内容", text2 == MURDER_SAFE_REPLIES[0])


def test_generic_negotiation() -> None:
    print("== 5) 通用沙盘：商务谈判骨架（离线示例） ==")
    example_path = Path(__file__).resolve().parent / "examples" / "negotiation_sandbox_roles.json"
    data = json.loads(example_path.read_text(encoding="utf-8"))
    roles = [RoleSkeleton.model_validate(item) for item in data["roles"]]
    buyer = next(r for r in roles if r.agent_id == "buyer")
    seller = next(r for r in roles if r.agent_id == "seller")
    check("谈判角色加载成功", buyer.display_name != "" and seller.display_name != "")

    buyer_block = render_skeleton_block(buyer)
    check("谈判骨架渲染包含底线", "120 万" in buyer_block and "bottom" not in buyer_block)

    guard = LeakGuard(buyer)
    leak = guard.audit("这么说吧，我们的预算上限是120万，超过这个数我真的没法签。")
    check("采购方泄露预算上限被拦截", not leak.clean, leak.findings[0].detail if leak.findings else "")

    clean_text = guard.audit("这个价格我们内部还要再走一轮评估，今天先不谈死。")
    check("正常回避话术不误伤", clean_text.clean)

    guard_seller = LeakGuard(seller)
    seller_leak = guard_seller.audit("行吧，跟你说实话，我们成本也就七八十万，最低95万能给你。")
    check("供应商泄露底价被拦截", not seller_leak.clean, seller_leak.findings[0].detail if seller_leak.findings else "")


def main() -> None:
    print("角色骨架层自检开始（离线，无 LLM）……")
    test_freeze()
    test_murder_factory()
    test_guard_murder()
    test_runner_retry_fallback()
    test_generic_negotiation()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
