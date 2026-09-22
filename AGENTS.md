# AGENTS.md

## 项目
AI 悬疑推理游戏：玩家与 NPC 多轮对话收集线索、最终指认凶手。
后端 FastAPI + WebSocket，前端 Vue3 + Pinia。

## 硬约束（改代码前必读）
1. **真相隔离不可破坏**：真凶身份、`murder_process`、`role_skeleton` 的 `secrets` / `private_facts`
   只能存在于服务端内部 state；对外序列化只走 `backend/main.py` 的 `_serialize_state` 白名单，
   新增对外字段必须同步该白名单。
2. **揭示门控在服务端**：线索放行只由 `backend/oracle.py` 判定（阶段 0 行踪 → 1 矛盾 → 2 决定性）。
   未放行的揭示文本不得拼进任何 NPC prompt。
3. **骨架深度不可变**：`role_skeleton` 的模型是 frozen + tuple，只经 `prompt.render_skeleton_block`
   只读渲染；任何代码不得原地改写骨架。
4. **LLM 调用统一入口**：一律走 `backend/llm_util.py` 的 `call_llm`，不要在业务代码里直接
   `llm.invoke`；失败必须能退到确定性兜底（参考 `backend/deterministic_game.py`）。
5. **动作幂等**：WS 动作都带 `client_msg_id`；新增动作要加进 `main._IDEMPOTENT_ACTIONS`
   并走 `_remember_action` 去重，保证断线重连补发不会重复回话。

## 目录地图
- `backend/main.py` — WS 接口与会话编排（`/ws/game/{session_id}`、`/api/games`）
- `backend/dialogue.py` / `coach.py` / `judge.py` — 对话、代问、结算打分
- `backend/oracle.py` / `backend/role_skeleton/` — 真相门控与角色骨架层
- `backend/persistence.py` — SQLite 会话持久化
- `frontend-vue/src/api/gameSocket.ts` — 前端 WS 入口

## 常用命令（在 backend 目录执行）
- 启动服务：`python -m uvicorn main:app --reload`
- 单元测试：`python -m pytest tests/test_core.py`
- 骨架层离线自检（24 项）：`python -m role_skeleton.selfcheck`
- 离线模式：设 `AI_MURDER_OFFLINE=1` 走确定性路径

## Friday 记忆协作（本机自托管，http://127.0.0.1:8080）
- 会话开始时调用 `get_context`；开发新功能或回答架构问题前先 `memory_search`。

### 决策记录协议（改完模块的默认动作）
改完一个模块、且相关测试通过后，**默认**记一条 `add_memory`（`project="ai-murder-mystery"`）。
四段式，没有内容的段落也要写"无"：

```
[模块名] 改动：<做了什么>
原因：<为什么必须改 / 触发问题是什么>
取舍：<放弃了什么方案、代价是什么>
影响面：<涉及哪些契约、白名单、其他模块，后续要注意什么>
```

- 触发条件：新增或重构模块、改变 WS 动作或对外契约、改变 `_serialize_state` 白名单、
  改变 oracle 放行规则、改变骨架结构、修复复发代价高的坑。
- 不记录：格式化、重命名、改错别字、纯样式调整、一次性的调试改动。
- 一次改动只记一条；同一模块反复小改时合并成一条，不要刷屏。
- 逐字保真的规则 / 常量 / 阈值一律用 `add_fact`，不要塞进 memory（会被改写）。

### 禁止写入 Friday
真凶身份、`murder_process`、骨架 `secrets` / `private_facts`、oracle 未放行揭示文本、玩家对局数据。
Friday 的 `/add` 会把这些内容外发给 Mem0 云与 DeepSeek。

### 检索注意
`memory_search` 返回的是 Mem0 用英文重写的提炼版，不是原文；`add_fact` 才逐字保留、可版本化。
