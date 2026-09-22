# config.py
import os
import httpx
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
http_client = httpx.Client(
    trust_env=False,
    timeout=httpx.Timeout(
        connect=15,
        read=120,
        write=30,
        pool=10
    )
)
# 环境变量改成DeepSeek KEY
api_key = os.getenv("DEEPSEEK_API_KEY")
base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
llm = None
if api_key:
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model="deepseek-chat",
            api_key=api_key,
            base_url=base_url,
            temperature=0,
            http_client=http_client,
        )
    except Exception:
        llm = None
KILLER_ROLE = "Killer"


def llm_available() -> bool:
    """LLM 是否真正可用：未配置 Key，或显式 AI_MURDER_OFFLINE=1 强制离线时都视为不可用。"""
    return llm is not None and os.environ.get("AI_MURDER_OFFLINE") != "1"
