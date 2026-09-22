# 角色硬约束骨架层（Role Skeleton Layer）

一句话定位：给每个 Agent 增加一层**独立存储、只读注入、强制校验**的角色骨架，
把“角色随时 OOC、秘密泄露、逻辑崩坏”这类问题从“靠 System Prompt 自觉”升级为**引擎层强约束闭环**。

适用场景不止剧本杀：商务谈判沙盘、项目推演、多方利益博弈仿真、教学模拟。

## 一、与 MetaGPT / AgentScope 的差异

| 能力 | MetaGPT | AgentScope | 本骨架层 |
| --- | --- | --- | --- |
| Agent 间消息通信 | 有（SOP 编排） | 有（Message 总线） | 不负责通信，只做约束 |
| 角色一致性保障 | 依赖 Prompt | 依赖 Prompt | 骨架注册表 + 冻结对象 + 输出审计 |
| 秘密/知识边界 | 无独立机制 | 无独立机制 | `secrets` + `knowledge.unknown` 语料绝不进 Prompt |
| OOC / 出戏拦截 | 无 | 无 | 元信息正则 + 锚点 + 引导重试 + 确定性兜底 |
| 骨架可被改写 | 无约束 | 无约束 | Pydantic frozen + 容器 tuple，代码也不可写 |
| 可观测审计 | 无 | 无 | 逐轮 `RoundRecord`（哪一轮、命中什么规则） |

核心结论：主流框架只解决“Agent 怎么说话、消息怎么传”，
本层解决“Agent **不能说什么、不能假装知道什么、底线是什么**”，且用代码而不是措辞保证。

## 二、架构

每个 Agent 拆成两部分：

1. **静态骨架层（本目录）**：人工配置或引擎规则生成的秘密、时间线、底线、禁止输出清单、知识边界。
2. **动态对话层（调用方）**：只负责表达，读取骨架渲染文本作为最高优先级背景。

```text
角色骨架(冻结对象)
   │  render_skeleton_block() 只读渲染
   ▼
System Prompt = 骨架块 + 动态对话指令
   │  调用 LLM 生成一句发言
   ▼
LeakGuard.audit() ──clean──▶ 放行
   └──违规──▶ build_steering() 类别化修正指引 → 重新生成（最多 max_retry 次）
                └──仍违规──▶ 确定性兜底发言（fallback），绝不放行违规文本
```

## 三、不可篡改的三层保障

1. **数据结构冻结**：`RoleSkeleton` 及其嵌套模型全部 `frozen`，且所有容器统一为 `tuple`（构造时由 list 自动转换）。对大模型和业务代码都是只读。
2. **LLM 拿不到对象**：骨架只通过 `render_skeleton_block()` 渲染成纯字符串拼进 Prompt；没有任何“改写骨架”的工具或参数。
3. **注册即密封**：游戏在 `start_game` 时一次性装配骨架，之后只读复用；引擎不留任何更新入口（升级为 `RoleSkeletonRegistry.seal()` 语义在 roadmap）。

## 四、检测器（LeakGuard）能拦截什么

| 来源 | 说明 | 示例 |
| --- | --- | --- |
| `forbidden_phrase` | 字面禁止清单，规范化后子串匹配 | “我就是凶手”“预算上限是120万” |
| `forbidden_pattern` | 正则禁止清单，可匹配数字/变体 | “预算…120万”类同义改写 |
| `meta_leak` | 出戏话术 | “作为AI我只能说……” |
| `secret` | 自己绝密内容被复述（锚点长串匹配） | 凶手把作案经过说成自己的“故事” |
| `unknown_fact` | 说出了知识边界之外的事实 | 嫌疑人“知道”只有凶手知道的细节 |

注意：`forbidden_*` 与 `unknown` 语料**只存在于检测器**，不会渲染进 Prompt，避免“教”模型绕过。

## 五、文件与接入点

| 文件 | 职责 |
| --- | --- |
| `schema.py` | 数据结构：`RoleSkeleton` / `Secret` / `KnowledgeBoundary` / `TimelineEvent` / `SkeletonPolicy` |
| `prompt.py` | `render_skeleton_block()` 只读渲染 |
| `guard.py` | `LeakGuard` 确定性检测 + `build_steering()` 修正指引 |
| `runner.py` | `constrained_answer()` 生成→审查→重试→兜底闭环 |
| `murder_factory.py` | 剧本杀适配：角色+案情 → 骨架（确定性，无 LLM 参与） |
| `examples/negotiation_sandbox_roles.json` | 商务谈判沙盘通用示例（JSON 直接 `RoleSkeleton.model_validate`） |
| `selfcheck.py` | 24 项离线自检（无需 API Key） |

### 剧本杀接入（已落地到 `main.py` Web 对话）

- `start_game` 后：`session_state["_skeletons"] = build_murder_skeletons(characters, story_details)`，
  骨架放在**会话层而非游戏 state**，天然不会经 WebSocket 序列化泄露给前端。
- `_answer_as_character(..., skeleton)`：把骨架块注入 System Prompt，
  再走 `constrained_answer(skeleton, generate, fallback=..., max_retry=2)`。
- 每次违规重试/兜底都会打日志：角色、轮次、命中规则来源。

骨架自动装配规则（`murder_factory.py`）：

- **凶手**：`secrets` 注入真实作案经过（保持自洽、能圆谎）；配自白正则 + 禁语字面清单；
  底线 = 绝不亲口承认、不描述真实手法。
- **嫌疑人**：`knowledge.unknown` 存“真凶是谁 + 真实经过”等检测语料（不进 Prompt）；
  配“编造目击行凶”正则；底线 = 不自认、不装目击者。
- **受害者**：不生成可对话骨架。

### 通用用法（谈判/推演/教学）

```python
import json
from role_skeleton.schema import RoleSkeleton
from role_skeleton.guard import LeakGuard

roles = [RoleSkeleton.model_validate(r) for r in json.load(open("negotiation_sandbox_roles.json"))["roles"]]
guard = LeakGuard(roles[0])          # 采购方
print(guard.audit("我们预算上限是120万，不能再高了。").clean)  # False，泄露被拦截
```

## 六、运行自检

```powershell
cd backend
venv\Scripts\python.exe -m role_skeleton.selfcheck
```

当前预期：`24 通过，0 失败`（离线，不调用任何大模型）。

## 七、已知边界与 roadmap

- 锚点匹配对**同义改写式 paraphrase** 的检测有限；要更强可加“语义 judge”（第二个 LLM / 向量召回）作为 `LeakGuard` 的插件校验器（接口未内置，已在文档中声明）。
- 绝密内容仍会展示给扮演者本人（凶手必须知道真相才能圆谎）；本层的防线在“对外输出”，不是让模型“不知道”。
- `game_nodes.py` 中 CLI / LangGraph 对话节点尚未同步套用骨架（当前实时 Web 对话已接入），下一步对齐。
- Roadmap：密封注册表 `RoleSkeletonRegistry`、按 `Secret.reveal_condition` 动态放行、
  逐轮审计落库、时间线冲突自检、前端侧只展示“公开档案”卡片。
