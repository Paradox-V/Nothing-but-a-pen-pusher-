"""配置加载工具"""
import os
import yaml


def load_config(config_path=None):
    """加载 config.yaml 配置文件"""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

    if not os.path.exists(config_path):
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
