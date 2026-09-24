# evaluation/providers.py
# Ragas 评测器需要的外部组件：判分用的大模型 + 向量模型（只在离线评估时构造）。
#
# 边界：
#   - 本模块只在 evaluation 包内被调用，游戏侧代码不导入它；
#   - ragas 是可选依赖（requirements-eval.txt），因此这里全部延迟导入：
#     没装 ragas 时抛出 EvalUnavailable 并给出安装提示，而不是让整个后端 import 崩掉；
#   - 判分用的模型走 config.llm（和游戏同一个 DeepSeek key），复用 call_llm 之外的
#     独立通道，不参与游戏动作链路；
#   - 向量模型默认用确定性的本地假向量（langchain_core 自带），保证无网也能跑、
#     结果可复现；要更好的语义指标可以切到 OpenAI 兼容的 embeddings 端点。

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Optional

from .harness import EvalUnavailable

EMBEDDING_MODES = ("deterministic", "openai")
DETERMINISTIC_EMBEDDING_DIM = 384

_LLM_WRAPPER_PATHS = (
    ("ragas.llms", "LangchainLLMWrapper"),
    ("ragas.llms.base", "LangchainLLMWrapper"),
    ("ragas.llms.llm", "LangchainLLMWrapper"),
)
_EMBEDDING_WRAPPER_PATHS = (
    ("ragas.embeddings", "LangchainEmbeddingsWrapper"),
    ("ragas.embeddings.base", "LangchainEmbeddingsWrapper"),
)
_BASE_EMBEDDING_PATHS = (
    ("ragas.embeddings.base", "BaseRagasEmbeddings"),
    ("ragas.embeddings", "BaseRagasEmbeddings"),
)

# 异步判分路径的 httpx 超时口径，与 config.py 里的同步 client 保持一致。
_ASYNC_TIMEOUT = {"connect": 15, "read": 120, "write": 30, "pool": 10}


@dataclass(frozen=True)
class JudgeStack:
    """判分用的模型栈（含人类可读标签，写进报告元信息）。"""

    llm: Any
    embeddings: Any
    llm_label: str
    embeddings_label: str
    # Ragas 的异步打分路径需要自己那条 httpx.AsyncClient，用完要显式关掉。
    async_client: Any = None

    def close(self) -> None:
        """关掉判分用的异步 client（评估跑完就收，别留着连接池）。"""
        client = self.async_client
        if client is None:
            return
        try:
            asyncio.run(client.aclose())
        except Exception:  # noqa: BLE001 - 关闭失败不影响已经拿到的指标
            pass


def _load_attr(paths) -> Optional[Any]:
    """按候选路径逐个 import，返回第一个找到的属性。"""
    for module_name, attr in paths:
        try:
            module = __import__(module_name, fromlist=[attr])
        except Exception:
            continue
        found = getattr(module, attr, None)
        if found is not None:
            return found
    return None


def _require_ragas() -> None:
    try:
        import ragas  # noqa: F401
    except Exception as exc:  # pragma: no cover - 取决于环境
        raise EvalUnavailable(
            "没有安装 ragas，无法计算语义指标。装依赖："
            "backend\\venv\\Scripts\\python.exe -m pip install -r requirements-eval.txt"
        ) from exc


def build_llm_wrapper() -> tuple[Any, str]:
    """把游戏用的 DeepSeek 模型包成 ragas 的判分 LLM。

    返回 (包装后的模型, 标签, 异步 client)。
    """
    _require_ragas()
    from config import llm, llm_available

    if not llm_available():
        raise EvalUnavailable(
            "Ragas 判分需要能用的模型：请在 backend/.env 配置 DEEPSEEK_API_KEY，"
            "并确认没有设置 AI_MURDER_OFFLINE=1。"
        )
    wrapper_cls = _load_attr(_LLM_WRAPPER_PATHS)
    if wrapper_cls is None:
        raise EvalUnavailable(
            "这个 ragas 版本没有找到 LangchainLLMWrapper；"
            "请改用支持 LangChain 模型的 ragas 版本，或在 providers.py 里补一条导入路径。"
        )
    model_name = str(getattr(llm, "model_name", "") or getattr(llm, "model", "") or "unknown")
    judge_model, async_client = _judge_model(llm)
    return wrapper_cls(judge_model), f"deepseek:{model_name}", async_client


def build_async_http_client() -> Any:
    """给 Ragas 的**异步**打分路径准备一个 httpx.AsyncClient。

    为什么要显式给：config.llm 只配了同步的 `http_client`（trust_env=False），
    而 Ragas 的指标走异步（`single_turn_ascore`），langchain 会给异步路径新建一个
    httpx.AsyncClient，默认 trust_env=True 会去读环境里的 SSL_CERT_FILE / HTTPS_PROXY。
    本机 SSL_CERT_FILE 指向一个中间人 CA，于是握手直接失败，表面症状是
    `APIConnectionError: Connection error.`，根因是 CERTIFICATE_VERIFY_FAILED。
    这里照搬 config 的口径：异步也关掉 trust_env。
    """
    import httpx

    return httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(**_ASYNC_TIMEOUT))


def _attach_async_client(llm: Any, async_client: Any) -> None:
    """兜底路径：直接在原模型实例上换掉异步 client（同步路径不受影响）。"""
    import openai

    root = openai.AsyncOpenAI(
        api_key=getattr(llm, "openai_api_key", None),
        base_url=getattr(llm, "openai_api_base", None),
        http_client=async_client,
    )
    llm.root_async_client = root
    llm.async_client = root.chat.completions


def _judge_model(llm: Any) -> tuple[Any, Any]:
    """按 config.llm 的参数复刻一个判分模型，并挂上 trust_env=False 的异步 client。

    返回 (判分模型, 异步 client)。复刻失败时退回“原地替换异步 client”，保证判分能跑。
    """
    async_client = build_async_http_client()
    kwargs = {
        "model": getattr(llm, "model_name", None),
        "api_key": getattr(llm, "openai_api_key", None),
        "base_url": getattr(llm, "openai_api_base", None),
        "temperature": getattr(llm, "temperature", 0.0),
        "http_client": getattr(llm, "http_client", None),
        "http_async_client": async_client,
    }
    try:
        return type(llm)(**{k: v for k, v in kwargs.items() if v is not None}), async_client
    except Exception:  # noqa: BLE001 - 换别的 langchain 版本时签名可能不同
        _attach_async_client(llm, async_client)
        return llm, async_client


def _deterministic_embeddings() -> Any:
    from langchain_core.embeddings import DeterministicFakeEmbedding

    return DeterministicFakeEmbedding(size=DETERMINISTIC_EMBEDDING_DIM)


def _openai_embeddings() -> Any:
    """OpenAI 兼容的 embeddings 端点（可选）。缺配置时直接报错，不静默降级。"""
    key = os.getenv("AI_MURDER_EVAL_EMBEDDING_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    model = os.getenv("AI_MURDER_EVAL_EMBEDDING_MODEL")
    base_url = os.getenv("AI_MURDER_EVAL_EMBEDDING_BASE_URL")
    if not key or not model:
        raise EvalUnavailable(
            "AI_MURDER_EVAL_EMBEDDINGS=openai 需要同时配置 "
            "AI_MURDER_EVAL_EMBEDDING_MODEL 与 AI_MURDER_EVAL_EMBEDDING_API_KEY（或 DEEPSEEK_API_KEY）。"
        )
    from langchain_openai import OpenAIEmbeddings

    kwargs: dict[str, Any] = {"model": model, "api_key": key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAIEmbeddings(**kwargs)


def _wrap_embeddings(embeddings: Any) -> Any:
    wrapper_cls = _load_attr(_EMBEDDING_WRAPPER_PATHS)
    if wrapper_cls is not None:
        return wrapper_cls(embeddings)

    # 没有 LangchainEmbeddingsWrapper 时，退而求其次：继承 ragas 的抽象基类。
    base_cls = _load_attr(_BASE_EMBEDDING_PATHS)
    if base_cls is None:
        raise EvalUnavailable(
            "这个 ragas 版本没有找到 embeddings 包装器；"
            "请在 providers.py 里补一条导入路径，或改用兼容的 ragas 版本。"
        )

    class _Adapter(base_cls):  # type: ignore[misc, valid-type]
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def embed_query(self, text: str) -> list[float]:
            return self._inner.embed_query(text)

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return self._inner.embed_documents(texts)

        async def aembed_query(self, text: str) -> list[float]:
            return self._inner.embed_query(text)

        async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
            return self._inner.embed_documents(texts)

    return _Adapter(embeddings)


def build_judge_stack(mode: Optional[str] = None) -> JudgeStack:
    """构造完整判分栈：LLM + embeddings。"""
    embedding_mode = (mode or os.getenv("AI_MURDER_EVAL_EMBEDDINGS") or "deterministic").strip().lower()
    if embedding_mode not in EMBEDDING_MODES:
        raise EvalUnavailable(
            f"AI_MURDER_EVAL_EMBEDDINGS 只能是 {'/'.join(EMBEDDING_MODES)}，当前：{embedding_mode!r}"
        )
    llm_wrapper, llm_label, async_client = build_llm_wrapper()
    inner = _deterministic_embeddings() if embedding_mode == "deterministic" else _openai_embeddings()
    label = (
        f"deterministic-fake-{DETERMINISTIC_EMBEDDING_DIM}d"
        if embedding_mode == "deterministic"
        else f"openai-compatible:{os.getenv('AI_MURDER_EVAL_EMBEDDING_MODEL') or 'unknown'}"
    )
    return JudgeStack(
        llm=llm_wrapper,
        embeddings=_wrap_embeddings(inner),
        llm_label=llm_label,
        embeddings_label=label,
        async_client=async_client,
    )


__all__ = [
    "DETERMINISTIC_EMBEDDING_DIM",
    "EMBEDDING_MODES",
    "JudgeStack",
    "build_async_http_client",
    "build_judge_stack",
    "build_llm_wrapper",
]
