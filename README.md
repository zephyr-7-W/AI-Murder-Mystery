# AI 悬疑推理游戏

玩家扮演侦探，与多名 NPC 多轮对话收集线索，最终指认凶手。服务端用「分阶段揭示」控制真相放行节奏，
并叠加一层角色硬约束骨架，防止 NPC 泄底或出戏。

## 玩法

1. 服务端为每局生成一套人物与案情（1 名凶手 + 1 名受害者 + 若干嫌疑人）。
2. 玩家自由选择嫌疑人对话，问行踪、追问矛盾、调查现场、请助手代问。
3. 线索按阶段放行：**阶段 0 行踪 → 阶段 1 矛盾 → 阶段 2 决定性**；未放行的秘密不会进入 NPC 上下文。
4. 在有限次数内指认凶手，服务端结算打分。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | FastAPI + WebSocket，httpx，Pydantic |
| LLM | LangChain / LangGraph，DeepSeek（OpenAI 兼容接口） |
| 前端 | Vue 3 + Pinia + Vite + TypeScript + Sass |
| 持久化 | SQLite（会话与对局历史） |

## 目录结构

```
backend/
  main.py               WebSocket 接口与会话编排（/ws/game/{session_id}），REST /api/games
  dialogue.py           玩家与 NPC 对话
  coach.py              助手代问
  judge.py              最终指认与结算打分
  oracle.py             真相门控：分阶段揭示表
  role_skeleton/        角色骨架层（秘密 / 时间线 / 底线 / 知识边界，frozen + tuple）
  persistence.py        SQLite 会话持久化
  deterministic_game.py 离线确定性兜底
  llm_util.py           统一 LLM 调用入口（重试 / 退避 / 限流）
  tests/test_core.py    单元测试
frontend-vue/
  src/api/gameSocket.ts 前端 WS 入口
  src/stores/           Pinia store
  src/components/       对话面板、证据板、时间线、嫌疑人档案等
  src/views/            Home / Game / Result
```

## 快速开始

### 后端

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

在 `backend/.env` 写入（该文件已被 git 忽略）：

```
DEEPSEEK_API_KEY=你的_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

启动服务：

```bash
python -m uvicorn main:app --reload
```

不配置 Key 也可以跑，或显式强制离线走确定性路径：

```bash
$env:AI_MURDER_OFFLINE = "1"   # PowerShell
```

### 前端

```bash
cd frontend-vue
npm install
npm run dev
```

## 常用命令（在 backend 目录执行）

```
python -m uvicorn main:app --reload    # 启动服务
python -m pytest tests/test_core.py    # 单元测试
python -m role_skeleton.selfcheck      # 骨架层离线自检（24 项）
```

## 核心设计

- **真相隔离**：真凶身份、作案过程、骨架的 secrets / private_facts 只存在于服务端内部 state；
  对外序列化只走 `backend/main.py` 的白名单，新增对外字段必须同步该白名单。
- **揭示门控在服务端**：线索是否放行只由 `backend/oracle.py` 判定，未放行的揭示文本不会拼进任何 NPC prompt。
- **骨架深度不可变**：`role_skeleton` 的模型为 frozen + tuple，只经只读渲染，任何代码不得原地改写。
- **LLM 调用统一入口**：一律走 `backend/llm_util.py` 的 `call_llm`，失败必须能退到确定性兜底。
- **动作幂等**：WS 动作都带 `client_msg_id`，服务端按消息 id 去重，断线重连补发不会重复回话。

## 说明

- 仓库不含任何 API Key：`backend/.env`、`venv/`、`node_modules/`、会话数据库与渲染产物均已在 `.gitignore` 中排除。
- 需求分析文档见 `AI悬疑推理游戏需求分析文档.docx`（由 `create_requirements_doc.py` 生成）。
- 更多架构笔记见 `backend/readme.md`，骨架层设计与文件地图见 `backend/role_skeleton/README.md`。
