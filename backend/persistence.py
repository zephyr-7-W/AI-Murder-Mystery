# persistence.py
# 后端 session 持久化
#
# 解决的问题：_GAME_SESSIONS 只存在进程内存里，uvicorn 一重启，玩家刷新/重连就
# “丢局 / 没有 NPC 回话”。这里把每局游戏的内部状态、骨架、真相 oracle、运行元信息
# （证词记录 / 已处理消息 id / 局号 / 结算分）落到 SQLite，服务重启后可按 session_id 原样恢复。
#
# 注意：写入的是“内部完整状态”（含真凶 role 与 murder_process），只存服务端，
# 绝不通过 WebSocket 下发；对外序列化仍然只走 main._serialize_state 的白名单。
#
# v2（向后兼容）：sessions 表新增 meta_json 列，旧库通过 init_db 内自动 ALTER 迁移。

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, List, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".game_sessions.db")
MAX_SESSIONS = 200
_WRITE_LOCK = threading.Lock()
_INIT_LOCK = threading.Lock()
_inited = False


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_meta_column(conn: sqlite3.Connection) -> None:
    """旧库迁移：为 sessions 表补充 meta_json 列（已存在则忽略）。"""
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "meta_json" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN meta_json TEXT NOT NULL DEFAULT '{}'")
    except sqlite3.Error as exc:
        print(f"[持久化] meta 列迁移失败：{exc}")


def init_db(db_path: str = DB_PATH) -> None:
    global _inited
    if _inited:
        return
    with _INIT_LOCK:
        if _inited:
            return
        directory = os.path.dirname(os.path.abspath(db_path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with _WRITE_LOCK, _connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=15000")
            conn.execute("CREATE TABLE IF NOT EXISTS sessions ("
                "    session_id    TEXT PRIMARY KEY,"
                "    started       INTEGER NOT NULL DEFAULT 0,"
                "    state_json    TEXT,"
                "    skeletons_json TEXT NOT NULL DEFAULT '[]',"
                "    oracle_json   TEXT NOT NULL DEFAULT '[]',"
                "    meta_json     TEXT NOT NULL DEFAULT '{}',"
                "    updated_at    REAL NOT NULL"
                ")")
            _ensure_meta_column(conn)
        _inited = True


def save_session(
    session_id: str,
    started: bool,
    state: Optional[dict[str, Any]],
    skeletons: Optional[list[dict[str, Any]]] = None,
    oracle: Optional[list[dict[str, Any]]] = None,
    meta: Optional[dict[str, Any]] = None,
    db_path: str = DB_PATH,
) -> None:
    """把一局的可序列化内部状态、骨架、oracle、运行元信息一次性写入数据库。"""
    init_db(db_path)
    state_json = json.dumps(state, ensure_ascii=False) if state is not None else None
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute(
            "INSERT INTO sessions "
            "(session_id, started, state_json, skeletons_json, oracle_json, meta_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "    started = excluded.started, "
            "    state_json = excluded.state_json, "
            "    skeletons_json = excluded.skeletons_json, "
            "    oracle_json = excluded.oracle_json, "
            "    meta_json = excluded.meta_json, "
            "    updated_at = excluded.updated_at",
            (
                session_id,
                1 if started else 0,
                state_json,
                json.dumps(skeletons or [], ensure_ascii=False),
                json.dumps(oracle or [], ensure_ascii=False),
                json.dumps(meta or {}, ensure_ascii=False),
                time.time(),
            ),
        )
        _prune(conn)


def _prune(conn: sqlite3.Connection) -> None:
    try:
        rows = conn.execute(
            "SELECT session_id FROM sessions ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
            (MAX_SESSIONS,)
        ).fetchall()
        for row in rows:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (row["session_id"],))
    except sqlite3.Error:
        pass


def load_session(session_id: str, db_path: str = DB_PATH) -> Optional[dict[str, Any]]:
    """返回与内存会话同构的 dict：{started, state, _skeletons, _oracle, meta}，不存在返回 None。"""
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT started, state_json, skeletons_json, oracle_json, meta_json FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    raw_state = row["state_json"]
    state = json.loads(raw_state) if raw_state else None
    return {
        "started": bool(row["started"]),
        "state": state,
        "_skeletons": json.loads(row["skeletons_json"] or "[]"),
        "_oracle": json.loads(row["oracle_json"] or "[]"),
        "meta": json.loads(row["meta_json"] or "{}"),
    }


def delete_session(session_id: str, db_path: str = DB_PATH) -> None:
    init_db(db_path)
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def list_sessions(db_path: str = DB_PATH) -> List[dict[str, Any]]:
    """列出后端保存的所有对局摘要（供 REST /api/games 使用）。"""
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT session_id, started, meta_json, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (MAX_SESSIONS,),
        ).fetchall()
    out: List[dict[str, Any]] = []
    for row in rows:
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        out.append({
            "session_id": row["session_id"],
            "started": bool(row["started"]),
            "updated_at": row["updated_at"],
            "game_no": meta.get("game_no") or "",
            "environment": meta.get("environment") or "",
            "max_characters": meta.get("max_characters") or 5,
            "difficulty": meta.get("difficulty") or "normal",
            "created_at": meta.get("created_at") or 0.0,
            "finished_at": meta.get("finished_at") or 0.0,
            "result": meta.get("result"),
            "score": meta.get("score"),
            "victory": meta.get("victory"),
            "guess_name": meta.get("guess_name"),
            "killer_name": meta.get("killer_name"),
            "meta": meta,
        })
    return out


__all__ = [
    "init_db",
    "save_session",
    "load_session",
    "delete_session",
    "list_sessions",
    "DB_PATH",
]