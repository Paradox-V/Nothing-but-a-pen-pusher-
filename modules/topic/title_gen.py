"""
热点选题模块 - DeepSeek 标题生成

为每条素材生成 3 个爆款标题
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# 爆款标题生成 prompt
TITLE_PROMPT = """你是一个资深{industry}领域内容专家。请为以下新闻素材生成3个爆款标题，要求：
1. 包含悬念、数字或权威感
2. 适合内容创作者使用
3. 每个标题一行，不要有编号
4. 标题长度适中（15-30字），吸引人
5. 结合{industry}行业和"{keyword}"关键词

新闻素材：
标题：{news_title}
内容摘要：{news_summary}

示例输出：
震惊！投资行业新科技竟能改变未来10年格局
3分钟了解投资科技的巨大潜力
专家预测：投资科技将成为下一个风口"""


def generate_titles(
    news_item: dict,
    industry: str,
    keyword: str,
    ai_config: dict | None = None,
) -> list[str]:
    """
    调用 DeepSeek 为单条素材生成 3 个标题。

    Args:
        news_item: 新闻条目（含 title, content）
        industry: 行业名称
        keyword: 用户关键词
        ai_config: AI 配置（model, api_key, api_base 等）
    """
    prompt = TITLE_PROMPT.format(
        industry=industry,
        keyword=keyword,
        news_title=news_item.get("title", ""),
        news_summary=(news_item.get("content") or "")[:200],
    )

    try:
        from ai.client import AIClient

        config = ai_config or _default_ai_config()
        client = AIClient(config)
        content = client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=500,
        )
        titles = _parse_titles(content)
        # 确保返回 3 个
        default = f"{industry}领域{keyword}新趋势：{news_item.get('title', '')[:20]}"
        while len(titles) < 3:
            titles.append(default)
        return titles[:3]

    except Exception as e:
        logger.error("标题生成失败: %s", e)
        title = news_item.get("title", "热点")
        return [
            f"{industry}领域{keyword}新动态：{title}",
            f"关于{industry}和{keyword}的重要分析",
            f"{title}：{industry}领域的新机遇",
        ]


def _parse_titles(content: str) -> list[str]:
    """解析 LLM 返回的标题列表"""
    titles = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # 去除编号
        if len(line) > 1 and line[0].isdigit() and line[1] in ".、)）":
            line = line[2:].strip()
        titles.append(line)
    return titles


def _default_ai_config() -> dict:
    """从 config.yaml 加载 AI 配置"""
    try:
        from utils.config import load_config
        cfg = load_config()
        ai = cfg.get("ai", {})
        return {
            "MODEL": ai.get("model", "deepseek/deepseek-chat"),
            "API_KEY": ai.get("api_key", ""),
            "API_BASE": ai.get("base_url", ""),
        }
    except Exception:
        return {}
