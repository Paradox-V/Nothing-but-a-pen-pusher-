"""LangChain 配置桥接 —— 从现有 AI 配置创建 ChatOpenAI 实例"""

from langchain_openai import ChatOpenAI
from ai.config import get_ai_config


def get_chat_model(temperature=None, max_tokens=None):
    """从现有 get_ai_config() 创建 ChatOpenAI 实例。

    DeepSeek-V3 暴露 OpenAI 兼容 API，因此使用 langchain-openai
    的 ChatOpenAI 类，指向 DeepSeek 的 base_url。
    """
    cfg = get_ai_config()
    model = cfg["MODEL"]  # e.g. "deepseek/deepseek-chat"
    model_name = model.split("/", 1)[1] if "/" in model else model

    return ChatOpenAI(
        model=model_name,
        api_key=cfg["API_KEY"],
        base_url=cfg["API_BASE"],
        temperature=temperature or cfg.get("TEMPERATURE", 0.7),
        max_tokens=max_tokens or cfg.get("MAX_TOKENS", 2000),
        timeout=cfg.get("TIMEOUT", 120),
    )
