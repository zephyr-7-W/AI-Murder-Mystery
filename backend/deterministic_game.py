# deterministic_game.py
# 离线 / 兜底剧本：不依赖任何大模型也能开局的一局完整游戏。
#
# 用途：
#   1. llm 未配置（DEEPSEEK_API_KEY 缺失）时仍可开新局、聊天、解锁线索、指认；
#   2. 生成大模型流程抛错时快速回退，避免“点开始没反应 / 服务端没回话”。
# 说明：这是“保底可用”而不是卖点；有 API Key 时仍走 AI 现场生成。

from __future__ import annotations

import random
from typing import Any

from models import Character, StoryDetails

# 角色顺序会直接影响前端“嫌疑人编号”，凶手故意放在 3 号位，不显眼也不固定。
_CHARACTERS: list[dict[str, str]] = [
    {
        "role": "Victim",
        "name": "顾清欢",
        "backstory": "庄园女主人，性情强势但待人并不刻薄。几个月前她发现丈夫在外另有住处，也察觉家族信托的账目有些对不上，近来一直独自在书房核对旧账。",
        "relation_to_victim": "受害者本人",
    },
    {
        "role": "Suspect",
        "name": "陆时谦",
        "backstory": "顾清欢的分居丈夫，商人。二人正在谈离婚与财产分割，他坚持要带走一半家产，当晚是回来取文件的。脾气不算好，但对离婚补偿很在意。",
        "relation_to_victim": "死者分居中的丈夫",
    },
    {
        "role": "Suspect",
        "name": "苏棠",
        "backstory": "顾清欢的妹妹，性格直率、藏不住话。她最近又欠下一笔赌债，曾向姐姐开口借钱被拒，姐妹俩为此吵过几次。当晚她本想找姐姐谈谈。",
        "relation_to_victim": "死者的妹妹",
    },
    {
        "role": "Killer",
        "name": "沈慕白",
        "backstory": "顾家的私人律师，替家族管理信托基金多年，看起来稳重妥帖。顾清欢近来发现账目异常，已放出话要请审计，他比谁都清楚那些钱去了哪里。",
        "relation_to_victim": "死者家族的私人律师",
    },
    {
        "role": "Suspect",
        "name": "陈妈",
        "backstory": "在顾家做了二十年管家的老人，嘴碎但心细。上月失手打碎夫人的古董花瓶被当众斥责，听说夫人打算让她提前回乡养老，她嘴上说着无所谓，心里很不是滋味。",
        "relation_to_victim": "死者家的老管家",
    },
]

_STORY: dict[str, Any] = {
    "victim_name": "顾清欢",
    "time_of_death": "晚上十点四十分前后",
    "location_found": "书房",
    "murder_weapon": "乌头碱（混入红酒的毒）",
    "cause_of_death": "乌头碱中毒，导致心律失常与呼吸衰竭",
    "crime_scene_details": (
        "书房里还飘着淡淡的甜酒味。书桌上摊着一份没签完的遗嘱草稿，"
        "杯沿留着一圈暗红的酒渍。地毯上散落着几页被揉皱的信托基金账目复印件，日期正是本月。\n"
        "书房角落的落地钟停在十点四十分左右，指针再没有走过。\n"
        "窗台外的露台上，烟灰缸里留着两个不同牌子的烟蒂。"
    ),
    "witnesses": (
        "陈妈说，晚上九点二十五分她按老规矩给夫人送热红酒，托盘放在书房门口就离开了，没看见屋里的人。\n"
        "陈妈还提到，十点三十五分她看见陆时谦从书房那一侧的走廊快步出来，绕去了花园侧门。\n"
        "陈妈说她在厨房洗碗时，隐约听见楼上有男人压低嗓门说话，大约在九点五十分前后，隔着地板听不真切。\n"
        "陈妈解释自己送完酒就回厨房收拾，一直忙到十点半，中途没再上过楼。\n"
        "陈妈说夫人这几天总把自己关在书房核对旧账，连晚饭都是让人端进去的。\n"
        "陈妈记得她上楼收空托盘时，发现书房门边挂钩上的钥匙不见了，当时没太在意。\n"
        "陈妈说十一点多是苏棠的惊叫声把她吵醒的，她披衣上楼，夫人已经倒在书桌前没了气息。\n"
        "陈妈说夫人脾气虽大但心肠不坏，前阵子打碎花瓶的事，夫人数落过几句也就过去了。\n"
        "苏棠说，九点五十分她在楼梯口听见书房里有争吵声，隔着门隐约是沈慕白的男声，随后门被猛地拉开。\n"
        "苏棠最后说，十一点整她想找姐姐借书，敲门没人应，推门才发现姐姐倒在书桌前。\n"
        "苏棠承认她最近又欠下一笔赌债，当晚本想找姐姐开口借钱，却一直没找到合适的时机。\n"
        "苏棠说姐姐这几天心事很重，老念叨家里账目被人动过手脚，还嘱咐她别跟外人提。\n"
        "苏棠提到十点四十五分她在二楼露台抽烟，隐约看见有人从花园侧门那边快步走回主楼。\n"
        "苏棠说她跟姐夫陆时谦不熟，只知道两人分居很久，最近为财产分割的事闹得很僵。\n"
        "苏棠说姐姐提起过书房那份没签完的遗嘱草稿，说受益人那一栏被人涂改得有点怪。\n"
        "苏棠说她当时吓得腿软，是陈妈先冲进书房探的鼻息，又喊了其他人来。\n"
        "陆时谦坚持说，那段时间他一直待在西翼书房里打电话，没有靠近过顾清欢的书房。\n"
        "陆时谦承认他当晚回来是为了取离婚协议和财产文件，说好第二天一早要交给律师。\n"
        "陆时谦说他九点半左右到的庄园，先在西翼书房等一个越洋电话，十点四十分挂断后直接去了车库。\n"
        "陆时谦说他和顾清欢半年前就分居了，最近谈离婚财产分割，她坚持要把信托那部分也算进共同财产。\n"
        "陆时谦说九点五十分左右他听见书房方向有动静，当时没在意，以为是陈妈在收拾。\n"
        "陆时谦承认他白天在花园跟沈慕白吵过一架，因为他发现信托账目里有一笔钱去向不明。\n"
        "陆时谦说他其实九点刚过就见过顾清欢一面，她站在书房窗边打电话，脸色很不好。\n"
        "陆时谦说陈妈看见他从走廊出来是误会，他只是绕去花园侧门拿落在车里的手机。\n"
        "沈慕白说，九点五十分他确实在书房与顾清欢谈遗嘱和信托账目，气氛越来越僵。\n"
        "沈慕白说谈崩之后他借口告辞回房，十点十分起就再没离开过自己房间。\n"
        "沈慕白解释自己去花园只是抽了根烟，大约十点三十五分到十点四十五分之间，没碰上什么人。\n"
        "沈慕白承认他替顾家管理信托基金多年，顾清欢近来发现账目对不上，已经放出话要请审计。\n"
        "沈慕白提到夫人曾当面质问他一笔海外转账，他解释那是常规信托分配，夫人并不完全相信。\n"
        "沈慕白说那晚的遗嘱草稿是顾清欢自己起草的，他只是建议她再斟酌一下受益人人选。\n"
        "沈慕白说他晚宴后换过外套，回房才发现袖口少了一颗深色袖扣，想不起掉在哪里。\n"
        "沈慕白说十点过后他在走廊尽头碰见陈妈端着空托盘下楼，两人还打了声招呼。"
    ),
        "initial_clues": (
        "书房地毯边缘有一枚不属于顾清欢的深色袖扣；"
        "遗嘱草稿的受益人一栏被人涂改过；"
        "信托账目复印件上有一行被铅笔圈出的可疑转账记录。"
    ),
    "npc_brief": (
        "顾清欢的丈夫陆时谦正在与她谈离婚财产分割，两人早已分居。"
        "妹妹苏棠嗜赌，近期欠下一笔外债，曾向姐姐借钱被拒。"
        "管家陈妈在顾家干了二十年，上月因打碎古董花瓶被斥责，据说夫人打算换掉她。"
        "私人律师沈慕白替家族管理信托基金多年，顾清欢近来发现账目对不上，正考虑追查。"
        "当晚四位嫌疑人都在庄园里，各有各的说法。"
    ),
    "murder_process": (
        "九点五十分，沈慕白在书房与顾清欢谈遗嘱与信托账目，气氛越来越僵。"
        "趁她起身去窗边拿东西，他把随身携带的乌头碱粉末倒进她杯里剩下的红酒中。"
        "谈崩后他借口告辞回了房。十点二十五分，陈妈把热红酒放在书房门口便离开，没有进屋。"
        "十点四十分左右，顾清欢独自喝下那杯酒，毒发倒在书桌旁。"
        "十点五十分，沈慕白从花园侧门潜回书房，收走酒杯与毒瓶、擦掉杯沿指纹后原路离开，"
        "再换回普通杯子摆在桌上，制造出书房里没有第二只酒杯的假象。"
    ),
}


def _drop_surplus(characters: list[Character], max_characters: int) -> list[Character]:
    """在保留凶手与受害者的前提下裁剪人数（与 AI 路径行为一致）。"""
    max_characters = max(3, int(max_characters))
    if max_characters >= len(characters):
        return characters
    surplus = len(characters) - max_characters
    removable = [
        index for index, c in enumerate(characters)
        if c.role.strip().lower() not in ("victim", "killer")
    ]
    drop = set(removable[-surplus:])
    return [c for index, c in enumerate(characters) if index not in drop]


def build_deterministic_game(environment: str, max_characters: int) -> dict[str, Any]:
    env = (environment or "一座偏远的贵族乡间庄园").strip() or "一座偏远的贵族乡间庄园"
    characters = [Character(**c) for c in _CHARACTERS]
    # 洗一下展示顺序，但仍保证受害者 = 0 号便于前端“案情速览”默认展示受害者档案
    random.shuffle(characters)
    characters = _drop_surplus(characters, max_characters)

    story = StoryDetails(**_STORY)
    # 若受害者被裁到非首位，仍保持 story.victim_name 指向真正的受害者
    victim = next((c for c in characters if c.role.strip().lower() == "victim"), None)
    if victim is not None:
        story.victim_name = victim.name

    intro = (
        f"暴雨把路封死的那晚，{env}里的灯忽然全灭了。"
        f"十点四十分前后，有人死在{story.location_found}——{story.victim_name}，"
        f"死因是{story.cause_of_death}。"
        f"停电让所有人都有离开房间的理由，也让每个人的证词都少了半个夜晚的见证。"
        f"管家、分居的丈夫、欠债的妹妹、跟了顾家多年的律师，谁都没说实话。"
        f"你需要在对话与现场调查里拼出真相。"
    )
    return {
        "environment": env,
        "max_characters": len(characters),
        "messages": [{"type": "ai", "content": intro}],
        "characters": characters,
        "story_details": story,
        "selected_character_id": None,
        "num_guesses_left": 3,
        "result": None,
    }


__all__ = ["build_deterministic_game"]
