"""AI 分析模块（可选 - 需要 litellm）"""
try:
    from ai.client import AIClient
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
