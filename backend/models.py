# models.py
from typing import List, Optional, Annotated, Sequence
import operator
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage

# pydantic使数据结构化：剧本、角色、案情等，自动类型校验，JSON解析
# TypedDict是类型提示工具
# State = 图运行时的共享白板 / 游戏存档内存**
# LangGraph 是图状态机，由Node(节点)、Edge(边)、State(状态)三大部分构成。
#  Node：一个个功能函数（生成剧本、和 NPC 对话、判断游戏胜负）
# Edge：规定节点执行顺序
# State：所有节点共享的全局数据容器，保存整个游戏全部运行时数据

# 定义角色模型
class Character(BaseModel):
    role: str = Field(
        description="Primary role of the character in the story",
    )
    name: str = Field(
        description="Name of the character."
    )
    backstory: str = Field(
        description="Backstory of the character focus, concerns, and motives.",
    )
    relation_to_victim: str = Field(
        default="",
        description="Short description of this character's relationship to the victim (e.g. spouse, sibling, business rival).",
    )

    @property
    def persona(self) -> str:
        relation = f"与受害者的关系：{self.relation_to_victim}\n" if self.relation_to_victim else ""
        return f"姓名：{self.name}\n身份：{self.role}\n{relation}背景：{self.backstory}\n"


# 定义NPC模型，角色列表容器，里面存放所有嫌疑人/NPC角色集合
class NPC(BaseModel):
    characters: List[Character] = Field(
        description="Comprehensive list of characters with their roles and backstories.",
        default_factory=list
    )


# 定义故事细节模型，
class StoryDetails(BaseModel):
    victim_name: str = Field(
        description="Name of the murder victim"
    )
    time_of_death: str = Field(
        description="Approximate time when the murder occurred"
    )
    location_found: str = Field(
        description="Where the body was discovered"
    )
    murder_weapon: str = Field(
        description="The weapon or method used in the murder"
    )
    cause_of_death: str = Field(
        description="Specific medical cause of death"
    )
    crime_scene_details: str = Field(
        description="Description of the crime scene and any relevant evidence found"
    )
    witnesses: str = Field(
        description="Information about potential witnesses or last known sightings"
    )
    initial_clues: str = Field(
        description="Initial clues or evidence found at the scene"
    )
    npc_brief: str = Field(
        description="Brief description of the characters and their relationships"
    )
    murder_process: str = Field(
        default="",
        description="Step-by-step account of how the murderer committed the crime (motive, method, timeline, cover-up). Only revealed to the player after the game ends.",
    )


# 子图对话状态，用于和单个NPC对话的子图状态
class ConversationState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    character: Character
    story_details: Optional[StoryDetails]


# 全局游戏状态
class GenerateGameState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    environment: str
    max_characters: int
    characters: List[Character]
    story_details: Optional[StoryDetails]
    selected_character_id: Optional[int]
    num_guesses_left: int
    result: str
