import asyncio
import json
import os
import random
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage, SystemMessage

from config import llm_available
from coach import clean_text, confirm_question
from dialogue import (
    _answer_as_character,
    _ask_hint,
    _build_victim_report,
    _bump_chat_progress,
    _compose_auto_questions,
    _exposed_reveals_ordered,
    _find_skeleton,
    _investigate_target,
    _killer_index,
    _killer_name,
    _reset_chat_progress,
    _story_prompt_text,
    _suspect_indexes,
    _talked_names,
)
from deterministic_game import build_deterministic_game
from game_nodes import create_characters, create_story, narrartor
from judge import score_game as judge_score
from llm_util import call_llm as ask_llm
from models import Character, StoryDetails
from oracle import (
    OracleItem,
    build_oracle_items,
    expose_item,
    next_stage_guide,
    oracle_choose,
    proximity_signal,
    question_is_substantive,
    relevance_score,
    revealable_items,
    stage_label,
    touches_reveal,
)
from persistence import delete_session, init_db, list_sessions, load_session, save_session
from role_skeleton.murder_factory import build_murder_skeletons
from role_skeleton.schema import RoleSkeleton


app = FastAPI(title="AI 悬疑推理游戏")

# 保存多局游戏状态（内存缓存；真正持久化见 persistence.py）
_GAME_SESSIONS: dict[str, dict[str, Any]] = {}
# 每个 session 一把 asyncio.Lock：同一局所有动作串行，避免多标签页并发写坏状态
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}

# 会话数据库初始化（幂等）
init_db()


# 幂等动作清单：断线重连补发 lastAction 时，服务端按 client_msg_id 去重，不回两遍
_IDEMPOTENT_ACTIONS = {
    "player_message",
    "auto_ask",
    "investigate",
    "ask_hint",
    "confront",
    "make_guess",
    "select_character",
}
_RECENT_ACTION_LIMIT = 120


def _session_lock(session_id: str) -> asyncio.Lock:
    return _SESSION_LOCKS.setdefault(session_id, asyncio.Lock())


def _fresh_session_state() -> dict[str, Any]:
    """新建（或恢复缺字段）的会话结构。"""
    return {
        "state": None,
        "started": False,
        "_skeletons": [],
        "_oracle": [],
        "_chat_progress": {},
        "_claims": {},
        "_contradictions": [],
        "_hint": {"points": 3, "max": 3},
        "_recent_actions": [],
        "_meta": {},
    }


def _remember_action(session_state: dict[str, Any], action: str, client_msg_id: Any) -> None:
    """记录已成功处理的幂等动作（按 client_msg_id + action 去重）。"""
    if not client_msg_id:
        return
    recents = session_state.setdefault("_recent_actions", [])
    recents.append({"id": str(client_msg_id), "action": action, "at": time.time()})
    if len(recents) > _RECENT_ACTION_LIMIT:
        del recents[: len(recents) - _RECENT_ACTION_LIMIT]


def _action_processed(session_state: dict[str, Any], action: str, client_msg_id: Any) -> bool:
    if not client_msg_id:
        return False
    key = str(client_msg_id)
    for record in session_state.get("_recent_actions", []):
        if record.get("id") == key and record.get("action") == action:
            return True
    return False


def _record_claim(session_state: dict[str, Any], owner: str, text: str) -> None:
    """证词记忆：记录角色本局承认/松口过的话，供后续一致性与对质使用。"""
    text = (text or "").strip()
    if not text or not owner:
        return
    claims = session_state.setdefault("_claims", {}).setdefault(owner, [])
    norm = _norm_key(text)
    if claims and any(_norm_key(str(c.get("text") or "")) == norm for c in claims):
        return
    claims.append({"text": text, "at": time.time()});
    if len(claims) > 12:
        del claims[: len(claims) - 12]


def _norm_key(raw: str) -> str:
    import unicodedata
    return "".join(
        ch for ch in (raw or "").lower()
        if unicodedata.category(ch) in {"Ll", "Lu", "Lm", "Lo", "Nd"}
    )


def _add_contradiction(session_state: dict[str, Any], a_owner: str, a_text: str, b_owner: str, b_text: str) -> str:
    """登记一处“两人证词被玩家拿出来对质”的矛盾点；返回矛盾 id。"""
    contradiction_id = f"con-{int(time.time() * 1000)}";
    session_state.setdefault("_contradictions", []).append({
        "id": contradiction_id,
        "a_owner": a_owner,
        "a_text": (a_text or "")[:160],
        "b_owner": b_owner,
        "b_text": (b_text or "")[:160],
        "found_at": time.time(),
    });
    return contradiction_id


def _result_extra(session_state: dict[str, Any]) -> dict[str, Any]:
    """已结算对局的补发载荷：重连/多端回放 game_over 时带上官方评分与指认信息。"""
    meta = session_state.get("_meta") or {}
    if not meta.get("score"):
        return {}
    extra: dict[str, Any] = {"result_data": meta["score"]}
    if meta.get("guess_reason"):
        extra["reason"] = meta["guess_reason"]
    if meta.get("guess_name"):
        extra["guess_name"] = meta["guess_name"]
    return extra


def _session_meta(session_state: dict[str, Any]) -> dict[str, Any]:
    meta = dict(session_state.get("_meta") or {})
    meta["claims"] = session_state.get("_claims", {});
    meta["contradictions"] = session_state.get("_contradictions", []);
    meta["hint"] = session_state.get("_hint", {"points": 3, "max": 3});
    meta["recent_actions"] = session_state.get("_recent_actions", []);
    return meta


def _chat_claims(session_state: dict[str, Any], owner: str) -> list[str]:
    claims = session_state.get("_claims", {}).get(owner, []);
    return [str(c.get("text") or "") for c in claims if str(c.get("text") or "").strip()]


def _next_stage_hint(oracle_items, owner: str) -> str:
    guide = next_stage_guide([item for item in oracle_items if item.owner == owner]);
    label = guide.get("label") or "";
    if not label:
        return "";
    return f"别急着打断，顺着刚才的话题往「{label}」上引——问具体的时间、地点或物件，对方才可能松口。";


def _stamp_messages(messages) -> list[dict[str, Any]]:
    """给消息补服务端序号与时间戳（重连/多端同步的稳定依据）。"""
    out: list[dict[str, Any]] = [];
    now_ms = time.time() * 1000;
    for index, raw in enumerate(messages or []):
        normalized = _normalize_message(raw);
        normalized.setdefault("seq", index + 1);
        normalized.setdefault("ts", now_ms);
        out.append(normalized);
    return out;
# 把LangChain的HumanMessage/AIMessage消息对象转换为简单字典，方便前端显示
# 服务端消息统一带 seq（本局内从 1 起的消息序号）与 ts（毫秒），多端/重连据此做幂等续接。
def _normalize_message(msg: Any) -> dict[str, Any]:
    if isinstance(msg, dict):
        normalized: dict[str, Any] = {"type": str(msg.get("type") or "ai"), "content": str(msg.get("content") or "")}
        if msg.get("seq") is not None:
            normalized["seq"] = int(msg.get("seq"))
        if msg.get("ts") is not None:
            normalized["ts"] = msg.get("ts")
        return normalized
    if hasattr(msg, "content"):
        kind = getattr(msg, "type", None)
        if kind is None:
            kind = "ai"
        return {
            "type": "ai" if str(kind).lower() in {"ai", "assistant"} else "human",
            "content": str(getattr(msg, "content", "")),
        }
    return {"type": "ai", "content": str(msg)}

# 后端内部完整状态→对外安全序列化，过滤敏感信息
def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    serialized = dict(state)
    if isinstance(serialized.get("characters"), list):
        serialized_characters = []
        for c in serialized["characters"]:
            char_dict = dict(c.model_dump()) if hasattr(c, "model_dump") else dict(c)
            # 对外只暴露“受害者 / 嫌疑人”，凶手也显示为嫌疑人
            role_lower = str(char_dict.get("role", "")).strip().lower()
            char_dict["role"] = "Victim" if role_lower == "victim" else "Suspect"
            serialized_characters.append(char_dict)
        serialized["characters"] = serialized_characters
    if isinstance(serialized.get("story_details"), StoryDetails):
        serialized["story_details"] = serialized["story_details"].model_dump()
    if isinstance(serialized.get("messages"), list):
        serialized["messages"] = _stamp_messages(serialized["messages"])
        serialized["server_seq"] = len(serialized["messages"]) if serialized["messages"] else 0
    return serialized

# ---------- 会话持久化（内部状态 <-> JSON） ----------
def _state_for_db(state: dict[str, Any]) -> dict[str, Any]:
    """把含 pydantic 对象的内部状态转成可 JSON 化的纯字典（真凶 role 与 murder_process 只存服务端）。"""
    story = state.get("story_details")
    return {
        "environment": state.get("environment"),
        "max_characters": state.get("max_characters"),
        "messages": _stamp_messages(state.get("messages") or []),
        "characters": [
            c.model_dump() if hasattr(c, "model_dump") else dict(c)
            for c in (state.get("characters") or [])
        ],
        "story_details": story.model_dump() if isinstance(story, StoryDetails) else None,
        "selected_character_id": state.get("selected_character_id"),
        "num_guesses_left": state.get("num_guesses_left", 3),
        "result": state.get("result"),
        "victim_report": state.get("victim_report"),
    }

def _state_from_db(payload: dict[str, Any]) -> dict[str, Any]:
    """从 DB 载荷还原内部状态（恢复成 Character / StoryDetails 强类型对象）。"""
    state = dict(payload)
    state["characters"] = [
        Character.model_validate(c) for c in (payload.get("characters") or [])
    ]
    story_payload = payload.get("story_details")
    state["story_details"] = StoryDetails.model_validate(story_payload) if story_payload else None
    return state

def _session_from_db(raw: dict[str, Any]) -> dict[str, Any]:
    """把 DB 行还原成内存会话结构（骨架 / oracle / 运行元信息重新物化）。"""
    meta = raw.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    session_state = _fresh_session_state()
    session_state["started"] = bool(raw.get("started"))
    state_payload = raw.get("state")
    if state_payload:
        state = _state_from_db(state_payload)
        state["messages"] = _stamp_messages(state.get("messages") or [])
        session_state["state"] = state
    session_state["_skeletons"] = [
        RoleSkeleton.model_validate(item) for item in (raw.get("_skeletons") or [])
    ]
    session_state["_oracle"] = [
        OracleItem.model_validate(item) for item in (raw.get("_oracle") or [])
    ]
    session_state["_meta"] = {
        k: v for k, v in meta.items()
        if k not in {"claims", "contradictions", "hint", "recent_actions", "chat_progress"}
    }
    session_state["_claims"] = meta.get("claims") or {}
    session_state["_contradictions"] = meta.get("contradictions") or []
    session_state["_hint"] = meta.get("hint") or {"points": 3, "max": 3}
    session_state["_recent_actions"] = (meta.get("recent_actions") or [])[-_RECENT_ACTION_LIMIT:]
    session_state["_chat_progress"] = meta.get("chat_progress") or {}
    return session_state

def _persist_session(session_id: str, session_state: dict[str, Any]) -> None:
    """把一局内存会话写入 SQLite（含骨架与真相 oracle），供进程重启后恢复。"""
    state = session_state.get("state")
    save_session(
        session_id,
        bool(session_state.get("started")),
        _state_for_db(state) if state is not None else None,
        skeletons=[item.model_dump() for item in (session_state.get("_skeletons") or [])],
        oracle=[item.model_dump() for item in (session_state.get("_oracle") or [])],
        meta=_session_meta(session_state),
    )

def _restore_session_from_db(session_id: str) -> dict[str, Any] | None:
    """服务重启后按 session_id 从 SQLite 恢复会话；没有则返回 None。"""
    raw = load_session(session_id)
    if raw is None:
        return None
    return _session_from_db(raw)

def _oracle_items_of(session_state: dict[str, Any], owner: str) -> list[OracleItem]:
    return [
        item for item in (session_state.get("_oracle") or [])
        if item.owner == owner
    ]

def _reveal_log(session_state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "owner": item.owner,
            "text": item.text,
            "exposed_at": item.exposed_at,
            "stage": int(getattr(item, "stage", 0) or 0),
        }
        for item in (session_state.get("_oracle") or [])
        if item.exposed
    ]

# 初始化一局完整游戏状态
def _build_ai_state(environment: str, max_characters: int) -> dict[str, Any]:
    # 离线 / 未配置 Key 时用确定性剧本，保证“开新局”永远有反应、不丢局
    if not llm_available():
        print("[剧情生成] 未配置 LLM 或 OFFLINE=1，使用离线确定性剧本")
        return build_deterministic_game(environment, max_characters)

    base_state = {
        "environment": environment,
        "max_characters": max_characters,
        "messages": [],
        "characters": [],
        "story_details": None,
        "selected_character_id": None,
        "num_guesses_left": 3,
        "result": None,
    }
    try:
        # Notebook-style flow: generate characters, then generate crime story, then narrator intro.
        character_state = create_characters(base_state)
        characters = character_state["characters"]
        if max_characters < len(characters):
            # 优先移除多余的非凶手/非受害者角色，保证受害者和凶手一定保留在游戏中
            surplus = len(characters) - max_characters
            removable = [
                index for index, character in enumerate(characters)
                if str(character.role).strip().lower() not in ("victim", "killer")
            ]
            drop = set(removable[-surplus:])
            characters = [
                character for index, character in enumerate(characters)
                if index not in drop
            ]

        story_state = {
            **base_state,
            "characters": characters,
        }
        story_state.update(create_story(story_state))

        narration_state = {
            **story_state,
            "messages": [],
        }
        narration_payload = narrartor(narration_state)
        story_state["messages"] = narration_payload.get("messages", [])
        return story_state
    except Exception as exc:  # 模型超时/报错时快速回退，不让玩家点开始后没有反应
        print(f"[剧情生成] LLM 流程失败，回退离线剧本：{exc}")
        return build_deterministic_game(environment, max_characters)

# 遍历characters列表，返回内部 role="killer" 角色的数组下标；后端内部才知道谁是凶手。

# 返回所有非受害者的下标集合，前端只能看到嫌疑人列表

async def _send_state(
    websocket: WebSocket,
    state: dict[str, Any],
    msg_type: str = "state_update",
    oracle=None,
    extra: dict[str, Any] | None = None,
) -> None:
    data = _serialize_state(state)
    if msg_type == "game_over":
        killer_index = _killer_index(state)
        if killer_index is not None:
            data["killer_name"] = state["characters"][killer_index].name
    else:
        # 作案过程只在结算时展示，游戏过程中不下发给前端
        if isinstance(data.get("story_details"), dict):
            data["story_details"].pop("murder_process", None)
    if oracle is not None:
        # reveal_log：已放行的结构化揭示，前端据此把对应锁定线索点亮（重连后幂等同步）
        data["reveal_log"] = [
            {
                "id": item.id,
                "owner": item.owner,
                "text": item.text,
                "exposed_at": item.exposed_at,
                "stage": int(getattr(item, "stage", 0) or 0),
            }
            for item in oracle
            if item.exposed
        ]
    if extra:
        data.update(extra)
    await websocket.send_json({"type": msg_type, "data": data})

# ---------- “AI 帮我提问”后端代问（LLM 措辞 + oracle 预检放行） ----------

# 健康接口检查
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

# WebSocket 主接口
@app.websocket("/ws/game/{session_id}")
async def game_socket(websocket: WebSocket, session_id: str):
    await websocket.accept()

    # 1) 内存会话优先；进程重启后按 session_id 从 SQLite 恢复（“丢局/没气泡”根因修复）
    session_state = _GAME_SESSIONS.get(session_id)
    if session_state is None:
        session_state = _restore_session_from_db(session_id)
        if session_state is None:
            session_state = _fresh_session_state()
        _GAME_SESSIONS[session_id] = session_state

    state = session_state.get("state")

    async def _emit(msg_type: str = "state_update", extra: dict[str, Any] | None = None) -> None:
        await _send_state(websocket, state, msg_type, oracle=session_state.get("_oracle"), extra=extra)

    async def _commit(
        msg_type: str = "state_update",
        action: str = "",
        client_msg_id: Any = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        # 先记录幂等、再落库、最后回执状态：任何一步失败都可在重连后安全重放
        if action and client_msg_id:
            _remember_action(session_state, action, client_msg_id)
        _persist_session(session_id, session_state)
        await _emit(msg_type, extra)

    # 2) 已有进行中的对局：连接即把完整状态推回，解决“刷新/重连后没内容、没有 NPC 气泡”
    async with _session_lock(session_id):
        if state is not None and session_state.get("started"):
            try:
                if state.get("result") in ("win", "lose"):
                    await _emit("game_over", extra=_result_extra(session_state))
                else:
                    await _emit()
            except Exception as exc:  # 客户端可能刚好断开，忽略
                print(f"[WS恢复] 推送已恢复对局失败：{exc}")

    def _character_by_id(char_id: Any):
        if state is None or char_id is None:
            return None
        try:
            char_id_int = int(char_id)
        except (TypeError, ValueError):
            return None
        characters = state.get("characters") or []
        if 0 <= char_id_int < len(characters):
            return characters[char_id_int]
        return None

    def _last_claim_of(name: str) -> str:
        claims = _chat_claims(session_state, name)
        return claims[-1] if claims else ""

    async def _ask_and_reply(
        character,
        question: str,
        oracle_items,
        force_item=None,
    ):
        """走一次完整对话回合：oracle 判定 -> 渐进/软反馈 -> 回复。返回放行的揭示项或 None。"""
        skeleton = _find_skeleton(session_state.get("_skeletons"), character)
        story = state.get("story_details")
        characters = state.get("characters") or []
        reveal_locked = revealable_items(oracle_items) if oracle_items else []
        matched = None
        if story is not None:
            matched = oracle_choose(question, reveal_locked, story, characters)
            if matched is None:
                progressive = _bump_chat_progress(
                    session_state, character.name, question, reveal_locked, story, characters,
                )
                if progressive is not None:
                    matched = progressive[0]
        soft_note = ""
        if matched is None and story is not None:
            level, near_item = proximity_signal(question, reveal_locked, story, characters)
            if level:
                soft_note = f"（{character.name}话音微微一滞，像是在斟酌措辞——你这个问题似乎让他有些不安。）"
        if matched is None and force_item is not None and story is not None:
            matched = force_item
        if matched is not None:
            expose_item(matched)
            _record_claim(session_state, character.name, matched.text)
            _reset_chat_progress(session_state, character.name)
        exposed_texts = _exposed_reveals_ordered(oracle_items, matched)
        state["messages"].append({"type": "human", "content": question})
        ai_reply = _answer_as_character(
            character,
            story,
            question,
            skeleton=skeleton,
            exposed_reveals=exposed_texts,
            just_revealed=matched.text if matched is not None else None,
        )
        if soft_note:
            ai_reply = soft_note + ai_reply
        state["messages"].append({"type": "ai", "content": f"{character.name}: {ai_reply}"})
        return matched

    try:
        while True:
            raw = await websocket.receive_text()
            payload = json.loads(raw)
            action = payload.get("action")
            client_msg_id = payload.get("client_msg_id")

            # 心跳：客户端定时 ping；服务端把最新整局状态回执，顺带做增量续接
            if action in ("ping", "heartbeat"):
                async with _session_lock(session_id):
                    state = session_state.get("state")
                    if state is not None and session_state.get("started"):
                        if state.get("result") in ("win", "lose"):
                            # 已结算的对局：心跳/续接统一回 game_over（带完整真相与官方评分），
                            # 避免 state_update 剥掉 murder_process 后把结算页的“作案过程”覆盖成空白
                            await _emit("game_over", extra=_result_extra(session_state))
                        else:
                            await _emit()
                    else:
                        await websocket.send_json({"type": "pong", "data": {}})
                continue

            async with _session_lock(session_id):
                state = session_state.get("state")
                if state is None and action not in ("start_game",):
                    await websocket.send_json({
                        "type": "action_error",
                        "code": "no_game",
                        "message": "还没有进行中的对局，请先开始一局新游戏。",
                        "action": action,
                    })
                    continue

                # 动作幂等：断线重连补发 lastAction 时不重复执行，只回执最新状态
                if client_msg_id and _action_processed(session_state, action, client_msg_id):
                    if action in ("player_message", "auto_ask", "investigate", "ask_hint", "confront", "make_guess"):
                        if state is not None and session_state.get("started") and state.get("result") in ("win", "lose"):
                            await _emit("game_over", extra=_result_extra(session_state))
                        elif state is not None and session_state.get("started"):
                            await _emit()
                        else:
                            await websocket.send_json({"type": "action_ack", "data": {}})
                    continue

                # ---------- 开局 ----------
                if action == "start_game":
                    environment = payload.get("environment") or "偏远乡间庄园"
                    max_characters = int(payload.get("max_characters") or 5)
                    difficulty = str(payload.get("difficulty") or "normal").strip().lower()
                    if difficulty not in {"easy", "normal", "hard"}:
                        difficulty = "normal"
                    difficulty_cfg = {
                        "easy": {"guesses": 4, "hints": 5},
                        "normal": {"guesses": 3, "hints": 3},
                        "hard": {"guesses": 2, "hints": 2},
                    }[difficulty]
                    state = _build_ai_state(environment, max_characters)
                    state["num_guesses_left"] = difficulty_cfg["guesses"]
                    session_state = _fresh_session_state()
                    session_state["state"] = state
                    session_state["started"] = True
                    # 引擎侧确定性装配角色骨架（不进 state，杜绝经序列化泄露给前端）
                    session_state["_skeletons"] = build_murder_skeletons(
                        state["characters"], state["story_details"]
                    )
                    # 真相 oracle：结构化揭示表，只随会话持久化，不进 state
                    session_state["_oracle"] = build_oracle_items(
                        state["story_details"], state["characters"]
                    );
                    session_state["_hint"] = {"points": difficulty_cfg["hints"], "max": difficulty_cfg["hints"]}
                    session_state["_meta"] = {
                        "game_no": payload.get("game_no") or "",
                        "environment": environment,
                        "max_characters": max_characters,
                        "difficulty": difficulty,
                        "created_at": time.time(),
                        "started_at": time.time(),
                    }
                    _GAME_SESSIONS[session_id] = session_state
                    await _commit("game_init", action, client_msg_id)
                    continue

                # ---------- 查看死者档案 ----------
                if action == "inspect_victim":
                    char = _character_by_id(payload.get("char_id"))
                    if char is not None:
                        state["selected_character_id"] = None
                        if str(char.role).strip().lower() == "victim" and not state.get("victim_report"):
                            state["victim_report"] = _build_victim_report(state)
                    await _commit("state_update", action, client_msg_id)
                    continue

                # ---------- 选择对话对象 ----------
                if action == "select_character":
                    char_id = payload.get("char_id")
                    try:
                        state["selected_character_id"] = None if char_id is None else int(char_id)
                    except (TypeError, ValueError):
                        state["selected_character_id"] = None
                    if state["selected_character_id"] is not None:
                        char = _character_by_id(state["selected_character_id"])
                        if char is not None:
                            state["messages"].append({
                                "type": "ai",
                                "content": f"你和 {char.name} 自然地聊了起来。别急着追问，像朋友闲聊那样开口，也许能从话里听出些线索。",
                            })
                    await _commit("state_update", action, client_msg_id)
                    continue
                # ---------- 玩家说话 ----------
                if action == "player_message":
                    text = str(payload.get("text") or "").strip()
                    if not text:
                        continue
                    if state["selected_character_id"] is None:
                        state["messages"].append({"type": "human", "content": text})
                        state["messages"].append({
                            "type": "ai",
                            "content": "请先选择一位角色后再进行对话。",
                        })
                        await _commit("state_update", action, client_msg_id)
                        continue
                    if text.upper() == "EXIT":
                        state["messages"].append({"type": "human", "content": "退出对话"})
                        state["messages"].append({
                            "type": "ai",
                            "content": "对话已结束，你可以重新选择人物，或直接进入指认。",
                        })
                        state["selected_character_id"] = None
                        await _commit("state_update", action, client_msg_id)
                        continue
                    character = _character_by_id(state["selected_character_id"])
                    if character is None:
                        continue
                    oracle_items = _oracle_items_of(session_state, character.name)
                    await _ask_and_reply(character, text, oracle_items)
                    await _commit("state_update", action, client_msg_id)
                    continue

                # ---------- AI 帮我提问（后端拟句 + oracle 预检 + 按阶段引导） ----------
                if action == "auto_ask":
                    if state["selected_character_id"] is None:
                        state["messages"].append({
                            "type": "ai",
                            "content": "先点一位嫌疑人开始对话，再让我帮你想一句能问出线索的话。",
                        })
                        await _commit("state_update", action, client_msg_id)
                        continue
                    character = _character_by_id(state["selected_character_id"])
                    if character is None:
                        continue
                    skeleton = _find_skeleton(session_state.get("_skeletons"), character)
                    oracle_items = _oracle_items_of(session_state, character.name)
                    reveal_locked = revealable_items(oracle_items)
                    exposed_texts = [item.text for item in oracle_items if item.exposed]
                    asked_questions = [
                        str(msg.get("content") or "").strip()
                        for msg in map(_normalize_message, state["messages"])
                        if msg.get("type") == "human"
                    ]
                    asked_keys = {clean_text(q) for q in asked_questions if clean_text(q)}
                    if oracle_items and not reveal_locked and not [i for i in oracle_items if not i.exposed]:
                        state["messages"].append({
                            "type": "ai",
                            "content": "（这位的话头你基本问完了——换个还没深聊的嫌疑人，或做做现场调查，再去整理白板。）",
                        })
                        await _commit("state_update", action, client_msg_id)
                        continue
                    stage_guide = _next_stage_hint(oracle_items, character.name)
                    questions = _compose_auto_questions(
                        character,
                        state["story_details"],
                        state["messages"],
                        skeleton=skeleton,
                        locked_items=reveal_locked,
                        exposed_texts=exposed_texts,
                        asked_questions=asked_questions,
                        extra_hint=stage_guide,
                    )
                    story = state.get("story_details")
                    characters = state.get("characters") or []
                    question = ""
                    if story is not None:
                        for cand in questions:
                            if oracle_choose(cand, reveal_locked, story, characters) is not None:
                                question = cand
                                break
                    if not question and reveal_locked and story is not None:
                        for item in reveal_locked:
                            cand = confirm_question(str(item.text or ""))
                            if cand and clean_text(cand) not in asked_keys:
                                question = cand
                                break
                    if not question and questions:
                        for cand in questions:
                            if clean_text(cand) not in asked_keys:
                                question = cand
                                break
                        if not question:
                            question = questions[0]
                    if not question:
                        question = "别急，咱们把那晚的事再捋一遍——你当时在哪儿，后来又去了哪？"
                    await _ask_and_reply(character, question, oracle_items)
                    await _commit("state_update", action, client_msg_id)
                    continue

                # ---------- 现场调查（结构化：可解锁揭示、统一记入评分） ----------
                if action == "investigate":
                    target = str(payload.get("target") or "").strip()
                    if not target:
                        continue
                    # 现场调查发生在对话之外，先退出当前对话，避免消息串台
                    state["selected_character_id"] = None
                    story = state.get("story_details")
                    characters = state.get("characters") or []
                    matched_item = None
                    if story is not None:
                        all_items = session_state.get("_oracle") or []
                        reveal_locked = revealable_items(all_items)
                        best = None
                        best_score = 0
                        for item in reveal_locked:
                            owner_inside = item.owner and item.owner in target
                            target_inside = target in str(item.text or "")
                            if owner_inside or target_inside:
                                score = relevance_score(target, str(item.text or ""), story, characters)
                                if score > best_score:
                                    best_score = score;
                                    best = item;
                        if best is not None:
                            matched_item = best
                    if matched_item is not None:
                        expose_item(matched_item)
                        _record_claim(session_state, matched_item.owner, matched_item.text)
                        _reset_chat_progress(session_state, matched_item.owner)
                    finding = _investigate_target(
                        state,
                        target,
                        extra_reveal=matched_item.text if matched_item is not None else "",
                    )
                    state["messages"].append({
                        "type": "ai",
                        "content": "【现场调查·" + target + "】" + finding,
                    })
                    await _commit("state_update", action, client_msg_id)
                    continue

                # ---------- 卡关提示（消耗提示点，随进度向下一阶段引导） ----------
                if action == "ask_hint":
                    hint_meta = session_state.get("_hint") or {"points": 3, "max": 3}
                    if int(hint_meta.get("points", 0)) <= 0:
                        state["messages"].append({
                            "type": "ai",
                            "content": "提示点已用完。多聊几句、做做现场调查会重新攒回提示点。",
                        })
                        await _commit("state_update", action, client_msg_id)
                        continue
                    hint_meta["points"] = max(0, int(hint_meta.get("points", 0)) - 1)
                    guide = _global_stage_guide(session_state)
                    hint = _ask_hint(state, stage_guide=guide)
                    state["messages"].append({"type": "ai", "content": "【提示】" + hint})
                    await _commit("state_update", action, client_msg_id, {"hint_points": hint_meta.get("points")})
                    continue

                # ---------- 时间线一键对质（后端化） ----------
                if action == "confront":
                    target_char = _character_by_id(payload.get("target_idx", payload.get("suspect_idx")))
                    if target_char is None:
                        await websocket.send_json({
                            "type": "action_error",
                            "code": "bad_target",
                            "message": "对质对象无效，请先从时间线里选一位嫌疑人。",
                            "action": action,
                        })
                        continue
                    state["selected_character_id"] = state["characters"].index(target_char)
                    if state["messages"] and not str(state["messages"][-1].get("content") or "").startswith("你和 " + target_char.name):
                        state["messages"].append({
                            "type": "ai",
                            "content": f"你和 {target_char.name} 自然地聊了起来。别急着追问，像朋友闲聊那样开口，也许能从话里听出些线索。",
                        })
                    source_char = _character_by_id(payload.get("source_idx"))
                    source_text = str(payload.get("source_text") or "").strip()
                    context_text = str(payload.get("context_text") or "").strip()
                    if source_char is not None and not source_text:
                        source_text = _last_claim_of(source_char.name)
                    if not source_text and not context_text:
                        state["messages"].append({
                            "type": "ai",
                            "content": "（时间线里还没找到可对质的证词——先和几位嫌疑人聊出各自的当晚安排，矛盾会自己浮出来。）",
                        })
                        await _commit("state_update", action, client_msg_id)
                        continue
                    if source_text:
                        clip_quote = source_text[:90] + ("……" if len(source_text) > 90 else "")
                        owner_name = source_char.name if source_char is not None else "有人"
                        question = "等一下——" + owner_name + "刚说：「" + clip_quote + "」。这话跟你之前说的对不上——那会儿你到底在哪、和谁在一起，能再仔细说一遍吗？"
                    else:
                        question = context_text
                    oracle_items = _oracle_items_of(session_state, target_char.name)
                    force_item = None
                    story = state.get("story_details")
                    characters = state.get("characters") or []
                    if story is not None and source_char is not None and source_text:
                        reveal_locked = revealable_items(oracle_items)
                        force_item = oracle_choose(question, reveal_locked, story, characters)
                        if force_item is None:
                            best = None;
                            best_score = 0;
                            for item in reveal_locked:
                                score = relevance_score(question, str(item.text or ""), story, characters)
                                if score > best_score:
                                    best_score = score;
                                    best = item;
                            if best is not None and best_score >= 1:
                                force_item = best;
                        if force_item is not None:
                            _add_contradiction(
                                session_state,
                                source_char.name,
                                source_text,
                                target_char.name,
                                str(force_item.text or ""),
                            )
                    await _ask_and_reply(target_char, question, oracle_items, force_item=force_item)
                    await _commit("state_update", action, client_msg_id)
                    continue
                # ---------- 指认凶手（可选推理理由 -> 后端结算评分） ----------
                if action == "make_guess":
                    raw_guess = payload.get("guess_idx")
                    reason = str(payload.get("reason") or "").strip()[:600]
                    try:
                        guess_idx = int(raw_guess) if raw_guess is not None else -1
                    except (TypeError, ValueError):
                        guess_idx = -1
                    killer_index = _killer_index(state)
                    if killer_index is None:
                        state["result"] = "lose"
                        await _commit("game_over", action, client_msg_id)
                        continue
                    # 前端指认列表只包含嫌疑人（受害者除外），编号从 0 开始
                    suspects = _suspect_indexes(state)
                    guessed_index = suspects[guess_idx] if 0 <= guess_idx < len(suspects) else None
                    guessed_name = state["characters"][guessed_index].name if guessed_index is not None else None
                    killer_name = state["characters"][killer_index].name
                    print(f"[指认] raw={raw_guess!r} guess_idx={guess_idx} 对象={guessed_name} 真凶={killer_name}")
                    if guessed_index is None:
                        state["messages"].append({
                            "type": "ai",
                            "content": "指认无效：请选择嫌疑人后再提交，本次不扣除机会。",
                        })
                        await _commit("state_update", action, client_msg_id)
                        continue

                    correct = guessed_index == killer_index
                    terminal = correct or state.get("num_guesses_left", 3) <= 1
                    if not correct:
                        state["num_guesses_left"] = max(0, state.get("num_guesses_left", 3) - 1)
                        terminal = terminal or state["num_guesses_left"] <= 0
                    if correct:
                        state["result"] = "win"
                    elif terminal:
                        state["result"] = "lose"
                    if state["result"]:
                        score = judge_score(
                            session_state.get("_oracle") or [],
                            reason=reason,
                            guess_correct=correct,
                            guesses_left=int(state.get("num_guesses_left", 0)),
                            llm_fn=(lambda prompt: ask_llm(
                                [SystemMessage(content=prompt)]
                            )) if llm_available() else None,
                            story=state.get("story_details"),
                            killer_name=killer_name,
                        )
                        meta = session_state.setdefault("_meta", {})
                        meta["result"] = state["result"]
                        meta["victory"] = correct
                        meta["guess_name"] = guessed_name
                        meta["killer_name"] = killer_name
                        meta["score"] = score
                        meta["finished_at"] = time.time()
                        meta["guess_reason"] = reason
                        extra_result = {"result_data": score, "reason": reason, "guess_name": guessed_name}
                        await _commit("game_over", action, client_msg_id, extra_result)
                        continue

                    state["result"] = None
                    state["messages"].append({
                        "type": "ai",
                        "content": "指认错误：这位嫌疑人并不是凶手，请继续调查后再作指认。",
                    })
                    await _commit("state_update", action, client_msg_id)
                    continue

                await websocket.send_json({
                    "type": "action_error",
                    "code": "unknown_action",
                    "message": "未知动作：" + str(action),
                    "action": action,
                })
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # 单动作出错不中断连接：回结构化错误，让前端可恢复
        import traceback
        print(f"[WS] 处理动作异常：{exc}")
        traceback.print_exc()
        try:
            await websocket.send_json({
                "type": "action_error",
                "code": "internal_error",
                "message": "处理动作时出了点问题，请重试一次；如果持续出现请重新开始本局。",
                "action": action if "action" in locals() else None,
            })
        except Exception:
            pass
    finally:
        if session_id in _GAME_SESSIONS and not _GAME_SESSIONS[session_id].get("started"):
            _GAME_SESSIONS.pop(session_id, None)
            delete_session(session_id)


def _global_stage_guide(session_state: dict[str, Any]) -> str:
    """汇总所有嫌疑人的下一解锁阶段，给提示系统一条方向性引导。"""
    oracle = session_state.get("_oracle") or []
    owners: list[str] = []
    seen: set[str] = set()
    for item in oracle:
        owner = str(getattr(item, "owner", "") or "")
        if owner and owner not in seen:
            seen.add(owner)
            owners.append(owner)
    guides: list[str] = []
    for owner in owners:
        guide = next_stage_guide([item for item in oracle if item.owner == owner])
        label = guide.get("label") or ""
        if label:
            guides.append(owner + "（" + label + "）")
    if not guides:
        return ""
    return "，".join(guides[:3])


# ---------- REST：后端对局列表 / 续局 / 删除（换设备不丢历史） ----------
@app.get("/api/games")
def api_list_games() -> dict[str, Any]:
    return {"games": list_sessions()}


@app.get("/api/games/{session_id}")
def api_get_game(session_id: str) -> dict[str, Any]:
    rows = list_sessions()
    for row in rows:
        if row["session_id"] == session_id:
            return row
    return {"error": "not_found", "session_id": session_id}


@app.delete("/api/games/{session_id}")
def api_delete_game(session_id: str) -> dict[str, Any]:
    _GAME_SESSIONS.pop(session_id, None)
    _SESSION_LOCKS.pop(session_id, None)
    delete_session(session_id)
    return {"ok": True, "session_id": session_id}
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
