# game_nodes.py
import random
import json
import getpass
from rich import print as rprint
from rich.panel import Panel
from rich.console import Console
from rich.prompt import Prompt
from rich.box import HEAVY_EDGE
from rich.table import Table
from rich.text import Text

from langchain_core.messages import (
    AIMessage,
    SystemMessage,
    HumanMessage,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import START, END

from config import KILLER_ROLE
from llm_util import raw_invoke
from models import (
    Character,
    NPC,
    StoryDetails,
    ConversationState,
    GenerateGameState
)

console = Console()

# ================== UI打印工具函数 ==================
def print_game_header():
    console.print(Panel("🕵️‍♂️ 悬疑推理调查游戏 🔍", style="bold blue"))


def print_narration(narration):
    console.print(Panel(
        f"[bold]案情引入[/bold]:\n\n{narration.content}",
        border_style="blue",
        padding=(1, 2),
        title="💬 开场旁白",
        title_align="left"
    ))
    console.rule(style="blue")


def print_introduction(character, narration):
    console.rule(f"[bold blue]与 {character.name} 的对话[/bold blue]", style="blue")
    console.print(Panel(
        f"[bold]{character.name}[/bold]:\n\n{narration.content}",
        border_style="blue",
        padding=(1, 2),
        title="💬 对话",
        title_align="left"
    ))
    console.rule(style="blue")


def get_player_input(character_name):
    console.print(Panel(
        f"[bold blue]向 {character_name} 提问[/bold blue]\n"
        f"[dim]输入 EXIT 可结束对话[/dim]",
        box=HEAVY_EDGE,
        border_style="blue",
        padding=(1, 2),
        title="💭 你的问题",
        title_align="left"
    ))
    question = Prompt.ask(
        "[bold yellow]调查者[/bold yellow]",
        default="",
        show_default=False
    )
    if question.lower() != "exit":
        console.print(Panel(
            f"[italic]{question}[/italic]",
            border_style="yellow",
            padding=(1, 1),
            title="🔍 提问",
            title_align="left"
        ))
    return question


def print_character_answer(character, reaction):
    console.print(Panel(
        f"[bold]{character.name} 的回答[/bold]:\n\n[italic]{reaction}[/italic]",
        border_style="cyan",
        padding=(1, 2),
        title="🗣️ 回答",
        title_align="left"
    ))


def print_characters_list(characters):
    console.print("\n[bold blue]角色列表[/bold blue]", justify="center")
    char_list = list(enumerate(characters))
    random.shuffle(char_list)
    table = Table(
        show_header=True,
        header_style="bold magenta",
        box=HEAVY_EDGE,
        expand=True
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("姓名", style="bold cyan", width=20)
    table.add_column("背景", style="green")
    display_to_original = {}
    for display_pos, (orig_idx, character) in enumerate(char_list):
        name_text = character.name
        if character.role.strip().lower() == "victim":
            name_text += " [red]（受害者）[/red]"
        table.add_row(
            str(display_pos + 1),
            name_text,
            Text(character.backstory, overflow="fold")
        )
        display_to_original[display_pos] = orig_idx
        if display_pos < len(char_list) - 1:
            table.add_row(style="dim")
    console.print(table)
    return display_to_original


def get_character_selection(characters, display_to_original):
    while True:
        console.print(Panel(
            "[bold blue]输入想调查的角色编号[/bold blue]\n"
            "[dim]输入 -1 直接指认凶手[/dim]",
            border_style="blue",
            title="👤 选择角色",
            title_align="left"
        ))
        try:
            choice_str = input("\n调查者: ").strip()
            if not choice_str:
                console.print("[red]输入不能为空！请输入编号或 -1。[/red]")
                continue
            choice = int(choice_str)
            if choice == -1:
                return {"selected_character_id": None}
            if 0 < choice <= len(characters):
                original_idx = display_to_original[choice - 1]
                selected_character = characters[original_idx]
                if selected_character.role.strip().lower() == "victim":
                    console.print("[red]无效选择：不能直接调查受害者[/red]")
                    continue
                console.print(f"你选择了 {selected_character.name}")
                return {"selected_character_id": original_idx}
            console.print("[red]编号无效，请输入范围内编号或 -1。[/red]")
        except ValueError:
            console.print("[red]输入无效，必须是整数。[/red]")


def get_player_yesno_answer(question):
    console.print(Panel(
        f"[bold blue]{question}[/bold blue]\n"
        f"输入 y 表示需要帮助，输入 n 表示自行提问或退出",
        box=HEAVY_EDGE,
        border_style="blue",
        padding=(1, 2),
        title="🤖🕵️ AI 侦探助手",
        title_align="left"
    ))
    answer = Prompt.ask(
        "[bold yellow]调查者[/bold yellow]",
        default="",
        show_default=False
    )
    return answer


def print_suspect_list(characters):
    table = Table(
        show_header=True,
        header_style="bold bright_red",
        box=HEAVY_EDGE,
        expand=True,
        title="[bold bright_red]🔍 嫌疑人[/bold bright_red]"
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("姓名", style="bold bright_red")
    characters = sorted(characters, key=lambda x: x.name)
    for idx, character in enumerate(characters, 1):
        table.add_row(str(idx), character.name)
    console.print(table)


def print_guesses_remaining(num_guesses):
    console.print(Panel(
        f"[bold]你还剩 {num_guesses} 次指认机会[/bold]",
        border_style="yellow",
        title="⏳ 剩余机会",
        title_align="left"
    ))


def print_result(is_win, is_lose, killer_name=None):
    if is_win:
        console.print(Panel(
            "[bold green]恭喜！你成功指认出了真凶。[/bold green]",
            border_style="green",
            title="🎯 指认成功",
            title_align="left"
        ))
    elif is_lose:
        console.print(Panel(
            f"[bold bright_red]调查失败！[/bold bright_red]\n[bright_red]真正的凶手是 {killer_name}。[/bright_red]",
            border_style="bright_red",
            title="❌ 游戏结束",
            title_align="left"
        ))


def print_incorrect_guess():
    console.print(Panel(
        "[bold yellow]你指认的这个人并不是凶手。[/bold yellow]",
        border_style="yellow",
        title="❗ 指认错误",
        title_align="left"
    ))


# ================== SubGraph Nodes 对话子图 ==================
def character_introduction(state: ConversationState):
    character = state['character']
    story = state['story_details']
    character_instructions = """
你正在扮演下面设定中的角色：
{subject_persona}

你正在接受玩家（调查者）关于下面这起案件的询问：
案件信息：
- 受害者：{victim}
- 死亡时间：{time}
- 发现地点：{location}

请先自然地和对方打个招呼并做简单自我介绍，语气口语化，直接对玩家说话。
注意：不要暴露你的真实身份，也不要说出对自己不利或引人怀疑的话。
除人名外，请一律使用简体中文。
"""
    system_message = character_instructions.format(
        subject_persona=character.persona,
        victim=story.victim_name,
        time=story.time_of_death,
        location=story.location_found,
    )
    narration = raw_invoke([
        SystemMessage(content=system_message),
        HumanMessage(content="请先向玩家介绍一下你自己。")
    ])
    print_introduction(character, narration)
    return {"messages": [narration]}


sherlock_ask_prompt = """
你是一位资深侦探。你正在协助玩家调查 {character_name} 与 {victim_name} 被杀一案。
案发时间约在 {time_of_death}，发现地点为 {location_found}，作案工具是 {murder_weapon}，死因是 {cause_of_death}。

现场情况：{crime_scene_details}
初步线索：{initial_clues}

与 {character_name} 的对话记录：
{conversation_history}

请基于以上信息，构思一个深刻且切中要害的问题，用来继续追问 {character_name}，帮助推进调查。
问题要符合资深侦探的语气，并尽量做到具体、犀利。
请使用简体中文（人名可保留原文），尽量一句话一行，方便阅读。
"""


def get_question(state: ConversationState):
    messages = state["messages"]
    character = state["character"]
    story = state["story_details"]
    system_message = sherlock_ask_prompt.format(
        character_name=character.name,
        victim_name=story.victim_name,
        time_of_death=story.time_of_death,
        location_found=story.location_found,
        murder_weapon=story.murder_weapon,
        cause_of_death=story.cause_of_death,
        crime_scene_details=story.crime_scene_details,
        initial_clues=story.initial_clues,
        conversation_history="\n".join([f"{msg.type}: {msg.content}" for msg in messages])
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_message),
        MessagesPlaceholder(variable_name="messages"),
    ])
    chain = prompt | llm
    question = chain.invoke(messages)
    console.print(Panel(
        f"[italic]{question.content}[/italic]",
        border_style="yellow",
        padding=(1, 1),
        title="🔍 AI 侦探助手提问 🤖🕵️",
        title_align="left"
    ))
    return question.content


def ask_question(state: ConversationState):
    character = state['character']
    while True:
        try:
            use_ai_sherlock = get_player_yesno_answer("需要 AI 侦探助手帮你提问吗？")
            if use_ai_sherlock.lower()[0] == 'y':
                question = get_question(state)
            else:
                question = get_player_input(character.name)
            return {"messages": [HumanMessage(content=question)]}
        except ValueError:
            print("输入无效，请输入有效问题")


def answer_question(state: ConversationState):
    messages = state['messages']
    character = state['character']
    last_message = messages[-1]
    story = state['story_details']
    answer_instructions = """
你正在扮演下面设定中的角色：
{subject_persona}

你正在接受玩家（调查者）关于下面这起案件的询问：
案件信息：
- 受害者：{victim}
- 死亡时间：{time}
- 发现地点：{location}
- 作案工具：{weapon}
- 死因：{cause}

现场描述：
{scene}

所有角色及人物关系：
{npc_brief}

请基于对话记录，以该角色应有的方式回答问题。依据：
1. 角色的性格与背景
2. 角色对案件的了解程度
3. 角色与其他人的关系
4. 角色可能的动机或不在场证明

重要：
- 保持角色人设
- 只透露该角色确实知道的信息
- 与案件细节保持一致
- 如果角色有理由说谎，可以说谎
- 除人名外，回答一律使用简体中文

玩家的问题：{question}
"""
    system_message = answer_instructions.format(
        subject_persona=character.persona,
        victim=story.victim_name,
        time=story.time_of_death,
        location=story.location_found,
        weapon=story.murder_weapon,
        cause=story.cause_of_death,
        scene=story.crime_scene_details,
        npc_brief=story.npc_brief,
        question=last_message.content
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_message),
        MessagesPlaceholder(variable_name="messages"),
    ])
    chain = prompt | llm
    answer = chain.invoke(messages)
    print_character_answer(character, answer.content)
    return {"messages": [answer]}


def where_to_go(state: ConversationState):
    messages = state['messages']
    last_message = messages[-1]
    if "EXIT" in last_message.content:
        return "end"
    else:
        return "continue"

# ================== Main Graph Nodes 主游戏图 ==================
character_instructions = """
你是一位推理游戏的角色设计师，任务是为一场中文谋杀悬疑推理游戏设计人物，目标是结合给定的场景环境，创作出形象鲜明、有沉浸感的角色阵容。

首先认真理解场景设定：

{{environment}}

请按以下步骤设计角色：
1. 结合场景环境，找到最能推动剧情、最有意思的主题与元素。
2. 依据 max_characters 确定角色总人数：

{{max_characters}}

3. 结合环境和人数构思符合场景的身份。请牢记：
 - 必须有且仅有一人是凶手；
 - 必须有且仅有一人是受害者；
 - 其余角色是可以被玩家盘问的嫌疑人；
 - 身份要贴合场景设定（例如庄园的管家、游轮上的船长、医院的护士等）。
4. 为每个身份安排合适的角色，保证人物多样、有看点。
5. 为每个角色提供：
 - 姓名（name）
 - 在案件中的身份（role）
 - 与受害者的关系（relation_to_victim）：用一句简短的中文短语描述（例如：受害者的妻子、受害者的弟弟、受害者的商业对手）；受害者本人填写“受害者本人”
 - 人物简介（backstory）：用中文简要说明其背景、性格与可能的动机

在输出最终列表前，先在心中规划：
1. 列出适合该场景的角色原型；
2. 构思凶手可能的作案动机，以及其它角色与案件的关联；
3. 考虑人物之间的关系与潜在冲突；
4. 思考场景内的人物互动如何为案情提供线索。

规划完成后，输出最终的角色列表。

注意：
- 角色与身份必须契合给定的场景环境；
- 人物要多样、有趣，能提升游玩体验；
- 尽量让多位角色都带有一点疑点或动机，方便后续设计误导与反转；
- 除“姓名”外，所有可见文本一律使用简体中文。
"""


def create_characters(state: GenerateGameState):
    environment = state['environment']
    max_characters = state['max_characters']
    system_message = character_instructions.replace("{{environment}}", environment)
    system_message = system_message.replace("{{max_characters}}", str(max_characters))
    prompt_extra = """
【硬性规则】
1. 只输出纯 JSON，不要输出任何思考过程、解释或 markdown ```json``` 代码块。
2. JSON 结构必须严格为：{"characters": [{"role":"","name":"","backstory":"","relation_to_victim":""}, ...]}
3. 必须且仅有一个 role="Killer"、一个 role="Victim"，其余一律 role="Suspect"。
4. 每位角色都必须填写 relation_to_victim：用简短中文描述其与受害者的关系；受害者本人填“受害者本人”。
5. 除 characters 数组外，不要添加任何多余的嵌套字段。
6. backstory、relation_to_victim 一律用简体中文；name 可以自由使用中文名或外文名。
"""
    full_sys = system_message + prompt_extra
    max_retry = 3
    for attempt in range(max_retry):
        try:
            resp = raw_invoke([
                SystemMessage(content=full_sys),
                HumanMessage(content="请生成这组角色，除姓名外全部用简体中文。")
            ])
            raw_text = resp.content.strip()
            raw_text = raw_text.removeprefix("```json").removesuffix("```").strip()
            data = json.loads(raw_text)
            npc = NPC(**data)
            chars = npc.characters

            # ============后端强制校验，修复LLM字段漂移BUG============
            # 身份只保留 Killer / Victim / Suspect，其余一律按 Suspect 处理
            for c in chars:
                if c.role.strip().lower() not in ("killer", "victim", "suspect"):
                    c.role = "Suspect"
            killer_cnt = sum(1 for c in chars if c.role.strip().lower() == "killer")
            victim_cnt = sum(1 for c in chars if c.role.strip().lower() == "victim")
            if killer_cnt != 1 or victim_cnt != 1:
                raise ValueError(f"角色role字段异常：Killer={killer_cnt}, Victim={victim_cnt}")
            # 关系字段兜底，保证每位角色都能标明与受害者的关系
            for c in chars:
                if not c.relation_to_victim.strip():
                    c.relation_to_victim = "受害者本人" if c.role.strip().lower() == "victim" else "与受害者关系不详"

            # 打乱角色顺序：凶手可能是任意一名嫌疑人，避免每次都排在第一
            random.shuffle(chars)

            return {"characters": chars}
        except Exception as e:
            print(f"create_characters 失败，重试 {attempt+1}/{max_retry}, error: {e}")
    raise RuntimeError("多次生成角色JSON失败，请检查prompt约束或LLM输出稳定性")


story_instructions = """
你正在为我们的推理游戏构思核心凶杀案件。请结合给定的场景与角色，设计一个出人意料、有反转、接近东野圭吾风格的悬疑案件：前期仅靠人物对话和表面线索很难锁定真凶，必须认真核对时间线、不在场证明、物证与人物关系，才能一步步推理出来。

场景：{{environment}}

角色：{{characters}}

请遵循以下要点设计案情：
1. 关于受害者，需要说明：
  - 尸体被发现的地点与状态
  - 大致死亡时间
  - 死因与作案工具
  - 现场状况
2. 包含关键证据与线索：
  - 现场的物证
  - 目击证词或最后目击情况
  - 可疑的细节
  - 可能相关的环境因素
3. 线索要兼顾：
  - 指向真凶的真实线索
  - 制造悬疑的干扰线索
  - 增加故事厚度的背景情况
4. 考虑：
  - 作案时间
  - 接近现场的条件
  - 可能的作案动机
  - 物证
  - 证词的可信度
5. 人物关系摘要（npc_brief）：
  - 说明每位角色与受害者的关系，但不要暴露谁是凶手
  - 提炼关键信息
  - 绝不能直接或间接提示真凶身份
6. 作案过程（murder_process）：
  - 写一段简短叙述，说明凶手实际如何作案：动机、如何接近现场、行凶过程、时间安排以及事后如何掩盖
  - 该字段只在游戏结束后展示给玩家，可以如实陈述真相
  - 在游戏过程中，witnesses、initial_clues、npc_brief 绝不能泄露这段完整真相
7. 反转与误导（重点要求）：
  - 让多位嫌疑人都有动机、可疑行为和看似合理的解释，制造层层误导
  - 真凶不必是对话中最可疑或最显眼的人，其动机要更隐蔽但合乎逻辑
  - 允许角色隐瞒、说谎或误导，但所有谎言必须自洽，能经得起细节对质
  - 真正的破绽要藏在细节里：时间线矛盾、物证痕迹、不在场证明漏洞、人物关系，而不是明面上直接点破
  - 开局旁白、案件概览、人物关系摘要都不要暗示凶手是谁
  - 结局应像反转小说：murder_process 完整还原动机、手法与骗局，所有伏笔前后一致，不能为了反转而自相矛盾

重要：
- 不要直接或间接提示凶手的身份
- 提供足够的细节，让案件可以通过推理解开
- 确保所有线索与场景、人物保持一致
- 案情要足够复杂有趣，又要足够清晰可解
- 凶手隐藏在嫌疑人之中，可以是任意一名嫌疑人，不要把凶手总是写成列表第一位或最可疑的人
- 除人名外，所有可见文本一律使用简体中文
"""


def create_story(state: GenerateGameState):
    environment = state['environment']
    characters = state['characters']
    character_list = "\n".join([char.persona for char in characters])
    victim_character = next(
        (c for c in characters if c.role.strip().lower() == "victim"), None
    )
    killer_character = next(
        (c for c in characters if c.role.strip().lower() == "killer"), None
    )
    system_message = story_instructions.replace("{{environment}}", environment)
    system_message = system_message.replace("{{characters}}", character_list)
    if victim_character is not None and killer_character is not None:
        system_message += (
            "\n\n【内部真相，仅用于生成逻辑，绝不能写入任何输出字段】："
            f"受害者是 {victim_character.name}，真凶是 {killer_character.name}。"
            f"所有线索、不在场证明与人物关系都必须与 {killer_character.name} 是真凶保持一致。"
        )
    prompt_extra = """
【硬性规则】
1. 不要输出嵌套对象（例如 {"victim":{...}}），所有字段必须是 JSON 顶层的平铺字段！
2. 顶层键必须严格为：victim_name, time_of_death, location_found, murder_weapon, cause_of_death, crime_scene_details, witnesses, initial_clues, npc_brief
3. 只输出纯 JSON 字符串，不要 markdown ```json``` 代码块，不要任何多余文字或思考内容。
4. 每个键都必须存在，不能遗漏任何字段。
5. witnesses 和 initial_clues 必须是字符串而不是数组，用一段话或分号分隔的句子表达。
6. 顶层 JSON 还必须包含 "murder_process" 字符串字段，说明凶手实际作案的完整过程。它只在游戏结束时揭示，因此绝不能泄露到 witnesses、initial_clues 或 npc_brief 中。
7. 除人名外，所有文本内容一律用简体中文。
"""
    full_sys = system_message + prompt_extra
    max_retry = 3
    for attempt in range(max_retry):
        try:
            resp = raw_invoke([
                SystemMessage(content=full_sys),
                HumanMessage(content="请用简体中文生成这起谋杀案件的完整剧情细节。")
            ])
            raw_text = resp.content.strip()
            raw_text = raw_text.removeprefix("```json").removesuffix("```").strip()
            data = json.loads(raw_text)

            # Notebook schema expects plain strings for narrative fields. Some models return arrays.
            for key in ["witnesses", "initial_clues", "npc_brief", "crime_scene_details", "murder_process"]:
                if key in data and isinstance(data[key], list):
                    data[key] = " ".join(str(item) for item in data[key])
                elif key in data and data[key] is not None and not isinstance(data[key], str):
                    data[key] = str(data[key])

            story = StoryDetails(**data)
            # 受害者姓名以角色设定为准，防止故事与角色身份不一致
            if victim_character is not None:
                story.victim_name = victim_character.name
            # 兜底：模型漏写作案过程时给出提示占位
            if not story.murder_process.strip() and killer_character is not None:
                story.murder_process = (
                    f"{killer_character.name} 的完整作案过程生成缺失，"
                    "可结合人物关系与线索补全其动机、手法、时间线与善后方式。"
                )
            return {"story_details": story}
        except Exception as e:
            print(f"create_story 失败，重试 {attempt+1}/{max_retry}, error:{e}")
    raise RuntimeError("多次生成故事JSON失败")


narrator_instructions = """
你是一位中文推理游戏的开场叙述者。请根据下面的案件信息，用简体中文写一段简洁、有氛围的案情引入（200 字以内），作为交给玩家（调查者）的开场介绍。叙述应当客观、生动，直接描述案件与现场，不要替玩家作判断。

案件信息：
- 受害者：{victim}
- 死亡时间：{time}
- 发现地点：{location}
- 作案工具：{weapon}
- 死因：{cause}

现场描述：
{scene}

要求：
1. 用第三人称中文叙述，营造推理氛围；
2. 不要提及或暗示真正的凶手是谁；
3. 除人名外，全文一律使用简体中文。
"""


def narrartor(state: GenerateGameState):
    story = state['story_details']
    system_message = narrator_instructions.format(
        victim=story.victim_name,
        time=story.time_of_death,
        location=story.location_found,
        weapon=story.murder_weapon,
        cause=story.cause_of_death,
        scene=story.crime_scene_details
    )
    narration = raw_invoke([
        SystemMessage(content=system_message),
        HumanMessage(content="请用简体中文撰写一段有氛围的开场旁白。")
    ])
    print_game_header()
    print_narration(narration)
    return {"messages": [narration]}


def sherlock(state: GenerateGameState):
    characters = state['characters']
    display_to_original = print_characters_list(characters)
    return get_character_selection(characters, display_to_original)


def guesser(state: GenerateGameState):
    num_guesses_left = state['num_guesses_left']
    all_characters = state['characters']
    non_victims = [char for char in all_characters if char.role.strip().lower() != 'victim']

    # 安全查找，忽略大小写，兜底None
    killer_character = next(
        (char for char in all_characters if char.role.strip().lower() == KILLER_ROLE.lower()),
        None
    )
    if killer_character is None:
        raise RuntimeError("游戏数据损坏：无法找到Killer角色，请重新启动游戏")

    characters = list(sorted(non_victims, key=lambda x: x.name))
    console.rule("[bold red]🔍 最终指认[/bold red]")
    print_guesses_remaining(num_guesses_left)
    print_suspect_list(characters)
    is_win, is_lose = False, False
    while True:
        try:
            choice = Prompt.ask(
                "\n[bold red]谁是真凶？[/bold red]（输入嫌疑人编号）",
                default="",
                show_default=False
            )
            choice = int(choice)
            if 0 < choice <= len(characters):
                selected_character_id = choice - 1
                selected_character = characters[selected_character_id]
                if selected_character.role.strip().lower() == KILLER_ROLE.lower():
                    is_win = True
                    break
                else:
                    print_incorrect_guess()
                    num_guesses_left -= 1
                    if num_guesses_left > 0:
                        print_guesses_remaining(num_guesses_left)
                if num_guesses_left == 0:
                    is_lose = True
                    break
            else:
                console.print("[red]编号无效，请输入正确的嫌疑人编号。[/red]")
        except ValueError:
            console.print("[red]输入无效，请输入数字。[/red]")
    print_result(is_win, is_lose, killer_character.name)
    is_end = is_win or is_lose
    if is_end:
        return {"result": "end", "num_guesses_left": num_guesses_left}
    else:
        return {"result": "sherlock", "num_guesses_left": num_guesses_left}

def conversation(state: GenerateGameState):
    from langgraph.graph import StateGraph
    from models import ConversationState
    selected_character_id = state['selected_character_id']
    if selected_character_id is not None:
        characters = state['characters']
        character = characters[selected_character_id]
        inputs = {
            "character": character,
            "story_details": state['story_details'],
        }
        # 子图本地构建调用
        conv_builder = StateGraph(ConversationState)
        conv_builder.add_node("character_introduction", character_introduction)
        conv_builder.add_node("ask_question", ask_question)
        conv_builder.add_node("answer_question", answer_question)
        conv_builder.add_edge(START, "character_introduction")
        conv_builder.add_edge("character_introduction", "ask_question")
        conv_builder.add_conditional_edges("ask_question", where_to_go, {"continue": "answer_question", "end": END})
        conv_builder.add_edge("answer_question", "ask_question")
        conv_graph = conv_builder.compile()
        response = conv_graph.invoke(inputs, {"recursion_limit": 50})
        return {"messages": [response['messages']]}
    else:
        return END
