# 项目运用的核心知识

> **架构提示（2026-09 更新）**：下面大部分篇幅是早期 LangGraph 教学梳理；当前 Web 版（backend/main.py 的
> `/ws/game/{session_id}`）的主链路已经不再逐节点跑主图/子图，而是 **WS 动作驱动 + 内存会话 + SQLite 持久化**：
> - 每个动作（player_message / auto_ask / investigate / ask_hint / confront / make_guess …）带 `client_msg_id`，
>   服务端按 session 串行加锁处理并按消息 id 去重，断线重连补发不会“同一句回两遍”；
> - 真相 oracle（backend/oracle.py）以**分阶段揭示表**放行线索（行踪→矛盾→决定性），未放行的秘密不进 NPC 上下文，
>   附带接近度软反馈，避免“聊了很多却一条不亮”或“一上来就泄底”；
> - 对话、代问、调查、提示、结算拆到 backend/dialogue.py、backend/coach.py、backend/judge.py；
>   统一 LLM 调用封装在 backend/llm_util.py（重试/退避/限流）；结算打分可注入 fake LLM 单测；
> - 对局列表 REST：GET /api/games、GET/DELETE /api/games/{session_id}（换设备不丢历史）。
> 新增/重构模块单测见 backend/tests/test_core.py；离线自检见 `role_skeleton/selfcheck`。


## 1. LangGraph
状态图State Graph：有向图编排业务流程，节点、边、条件分支实现游戏状态流转；
Typed State（Pydantic状态）：
-- GenerateGameState：主图全局游戏状态（角色、案情、剩余次数、选中角色ID、全局消息
-- ConversationState：子图独立状态，单NPC对话会话隔离
子图SubGraph：一张主图内嵌一张对话子图，处理玩家与多个单NPC多轮循环对话
条件边conditional_edges：根据返回值做分支跳转（退出对话回到主流程、猜错凶手返回调查）；
递归限制recursion_limit：防止对话无限循环

## 2. LLM应用工程
System Prompt工程：复杂结构化Prompt约束大模型输出；区分普通对话Prompt + JSON强制输出Prompt；
结构化输出容错：LLM输出不稳定，去除“json标记、异常list转字符串、最多3次重试机制”；
Pydantic数据模型校验：Character/NPC/StoryDetails/ConversationState做数据校验，拦截LLM脏输出；
提示词隔离真相：内部仅给LLM看凶手真相，输出内容严禁泄露凶手，实现误导线索生成。

## 3. Python基础工程
面向对象Pydantic模型，强类型数据封装；
JSON清洗、异常捕获、重试逻辑；
rich终端UI库：面板、表格、交互式命令行输入输出（原型控制台界面）；
随机逻辑：角色列表随机打乱，避免凶手位置固定。

## 4. web层

## 5. 业务设计

# 完整工作流：主图 + 对话子图
## 主图 GenerateGameState（7 个节点）
create_characters：游戏初始化第一步。接收场景environment、最大角色数；调用 LLM 生成整套人物；强制保证 1 个凶手、1 个受害者，其余嫌疑人；JSON 容错重试；返回characters角色列表存入状态。

create_story：生成完整案件剧情。基于已经生成好的角色，让 LLM 生成凶杀案全部细节：死亡时间、地点、凶器、现场、证人、线索、人物关系摘要、作案真相 murder_process；清洗修复 LLM 异常输出；返回story_details案情对象。

narrartor：生成开场案情旁白，渲染游戏开篇，把开场消息存入 state 的 messages。

sherlock：角色选择节点：展示全部角色列表；接收玩家输入；返回selected_character_id。

conversation：子图入口调度节点：拿到选中角色 ID，动态构建对话子图实例并 invoke 运行子图；完整跑完玩家和该 NPC 的多轮对话；对话结束后把子图的全部对话消息合并回主图 state。

guesser：最终指认凶手节点。展示嫌疑人列表；读取玩家输入编号；比对是否真凶；猜对：游戏结束；猜错扣次数；次数没耗尽返回sherlock回到调查；次数归零直接失败结束。返回result用于条件边判断跳转。

START
  ↓
create_characters → create_story → narrartor → sherlock（选角色）
  ├─有选中角色ID → conversation（运行对话子图） → 回到 sherlock
  └─selected_character_id=None → guesser（进入指认）
    ├ result="sherlock" → 返回 sherlock继续调查
    └ result="end" → END 游戏结束

## 对话子图 ConversationState（5 个节点，处理单 NPC 多轮聊天）
character_introduction：NPC 自我介绍：根据角色人设 + 案件背景，调用 LLM 生成人物开场白。

ask_question：获取玩家问题：交互询问是否开启 AI 侦探助手；y 则调用get_question由 LLM 生成犀利提问；n 读取玩家手动输入；把问题封装HumanMessage。

get_question：AI 侦探助手：基于对话历史、案件细节，生成一条追问问题。（被 ask_question 内部调用）

answer_question：拟NPC 回答核心：传入完整人设、案件、历史对话；LLM 模角色回答，可以说谎隐瞒；输出 AIMessage 存入子图 messages。

where_to_go：条件路由函数，不是真正节点：判断玩家输入是否包含EXIT。continue：继续循环问答；end：退出子图返回主流程。

START → character_introduction → ask_question
  ├ where_to_go: continue → answer_question → ask_question（循环提问回答）
  └ where_to_go: end → END（退出子图回到主图）

# 6. 角色硬约束骨架层（role_skeleton）

在现有 LangGraph 编排之上，新增一层**可复用的“角色硬约束骨架”**：
每个 Agent = 静态骨架（秘密/时间线/底线/禁止输出清单/知识边界，独立存储、不可改写）
+ 动态对话层（只负责表达）。

- 已落地：Web 实时对话（main.py 的 _answer_as_character）已注入骨架并接入
  生成→防泄露审查→修正重试→确定性兜底闭环；
- 检测器不依赖第二个 LLM：字面短语 + 正则 + 出戏话术 + 秘密/知识边界锚点长串匹配；
- 支持剧本杀以外的通用沙盘（商务谈判/项目推演等，见 examples JSON）；
- 离线自检 24 项：backend 目录执行
  `venv\Scripts\python.exe -m role_skeleton.selfcheck`

详细设计与文件地图见 role_skeleton/README.md。

