"""配置加载工具

敏感配置通过环境变量覆盖：
  AI_API_KEY   - AI API 密钥
  AI_BASE_URL  - AI API 基础 URL
  ADMIN_TOKEN  - 管理员 Token
"""
import os
import logging

import yaml

logger = logging.getLogger(__name__)


def load_config(config_path=None):
    """加载 config.yaml 配置文件，环境变量优先"""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

    if not os.path.exists(config_path):
        logger.warning("配置文件不存在: %s", config_path)
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    # 环境变量覆盖敏感配置
    ai_cfg = config.setdefault("ai", {})
    if os.environ.get("AI_API_KEY"):
        ai_cfg["api_key"] = os.environ["AI_API_KEY"]
    if os.environ.get("AI_BASE_URL"):
        ai_cfg["base_url"] = os.environ["AI_BASE_URL"]
    if os.environ.get("AI_MODEL"):
        ai_cfg["model"] = os.environ["AI_MODEL"]

    # 管理员 Token
    admin_token = os.environ.get("ADMIN_TOKEN")
    if admin_token:
        config["admin_token"] = admin_token

    return config
