"""AI 配置提供器

统一从 config.yaml / 环境变量加载 AI 配置，
消除各模块重复的 _default_ai_config() 逻辑。
"""

import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 缓存配置（避免重复读取文件）
_cached_config: dict | None = None


def get_ai_config() -> dict[str, Any]:
    """获取统一的 AI 配置字典，供 AIClient 使用。

    优先级：环境变量 > config.yaml > 默认值
    结果会被缓存，进程内只读一次配置文件。
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    # 从 config.yaml 读取
    try:
        from utils.config import load_config
        cfg = load_config()
        ai = cfg.get("ai", {})
    except Exception:
        ai = {}

    _cached_config = {
        "MODEL": os.environ.get("AI_MODEL") or ai.get("model", "deepseek/deepseek-chat"),
        "API_KEY": os.environ.get("AI_API_KEY") or ai.get("api_key", ""),
        "API_BASE": os.environ.get("AI_BASE_URL") or ai.get("base_url", ""),
        "TEMPERATURE": ai.get("temperature", 1.0),
        "MAX_TOKENS": ai.get("max_tokens", 5000),
        "TIMEOUT": ai.get("timeout", 120),
        "NUM_RETRIES": ai.get("num_retries", 2),
        "FALLBACK_MODELS": ai.get("fallback_models", []),
    }

    if not _cached_config["API_KEY"]:
        logger.warning("AI API Key 未配置，AI 功能将不可用")

    return _cached_config


def reset_config():
    """清除缓存（测试用）"""
    global _cached_config
    _cached_config = None
