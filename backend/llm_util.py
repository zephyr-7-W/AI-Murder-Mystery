# llm_util.py
# 统一 LLM 调用封装
#
# 所有后端大模型调用统一走这里：
#   - 超时由 config.http_client 保证（connect/read/write）；
#   - 内置重试 + 指数退避，单次失败不直接断动作；
#   - 记录每次调用的耗时与失败日志，便于排查“卡住/空回复”；
#   - 可选按 key 的分钟级限流（演示时防止打爆 key，默认关闭）。
#
# 说明：config.llm 由 langchain_openai.ChatOpenAI 构造；这里不新增第三方依赖。

from __future__ import annotations

import threading
import time
from typing import Any, Optional, Sequence

from config import llm, llm_available

_CALL_HISTORY: dict[str, list[float]] = {}
_HISTORY_LOCK = threading.Lock()


def available() -> bool:
    """LLM 是否可用（未配 Key 或 AI_MURDER_OFFLINE=1 都不可用）。"""
    return llm_available()


def _allow(key: str, per_minute: int) -> bool:
    """滑动窗口限流：per_minute<=0 表示不限。"""
    if per_minute <= 0:
        return True
    now = time.time()
    with _HISTORY_LOCK:
        stamps = [t for t in _CALL_HISTORY.get(key, []) if now - t < 60.0]
        if len(stamps) >= per_minute:
            _CALL_HISTORY[key] = stamps
            return False
        stamps.append(now)
        _CALL_HISTORY[key] = stamps
    return True


def call_llm(
    messages: Sequence[Any],
    *,
    label: str = "",
    max_chars: Optional[int] = None,
    retries: int = 2,
    rate_key: str = "default",
    rate_per_minute: int = 0,
) -> str:
    """执行一次 LLM 调用并返回纯文本内容。

    - 模型不可用（offline / 未配 key）时抛 RuntimeError，由调用方走确定性兜底；
    - 失败按 0.6s / 1.4s 退避重试（retries 次）；
    - 成功会打印耗时；失败会打印异常信息（便于排查空回复 / 卡住）。
    """
    if llm is None or not available():
        raise RuntimeError("LLM 未配置或处于离线模式")
    if not _allow(rate_key, rate_per_minute):
        raise RuntimeError("请求过于频繁，请稍后再试")

    attempts = retries + 1
    for attempt in range(attempts):
        started = time.time()
        try:
            result = llm.invoke(list(messages))
            text = str(getattr(result, "content", "") or "").strip()
            elapsed = (time.time() - started) * 1000
            if max_chars is not None and len(text) > max_chars:
                text = text[:max_chars]
            print(f"[LLM] ok label={label or '-'} ms={elapsed:.0f} chars={len(text)}")
            return text
        except Exception as exc:  # noqa: BLE001 - 调用失败统一记录
            elapsed = (time.time() - started) * 1000
            print(f"[LLM] fail label={label or '-'} ms={elapsed:.0f} attempt={attempt + 1}/{attempts} err={exc}")
            if attempt < retries:
                time.sleep(0.6 * (2 ** attempt))
            else:
                raise




class _LlmResult:
    """让 call_llm 以旧的 result.content 用法兼容现网代码。"""

    def __init__(self, text):
        self.content = text


def raw_invoke(messages, *, label="llm_invoke", max_chars=None, retries=2, rate_key="default", rate_per_minute=0):
    """向后兼容封装：调用统一 call_llm 并返回带 .content 的轻量结果对象。"""
    text = call_llm(
        messages,
        label=label,
        max_chars=max_chars,
        retries=retries,
        rate_key=rate_key,
        rate_per_minute=rate_per_minute,
    )
    return _LlmResult(text)


__all__ = ["call_llm", "raw_invoke", "available", "llm"]
