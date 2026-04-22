# coding=utf-8
"""
AI 分析器模块

调用 AI 大模型对热点新闻进行深度分析
基于 LiteLLM 统一接口，支持 100+ AI 提供商
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ai.client import AIClient

logger = logging.getLogger(__name__)


@dataclass
class AIAnalysisResult:
    """AI 分析结果"""
    core_trends: str = ""                # 核心热点与趋势
    signals: str = ""                    # 异动与弱信号
    outlook: str = ""                    # 研判与展望
    raw_response: str = ""               # 原始响应
    success: bool = False                # 是否成功
    error: str = ""                      # 错误信息


class AIAnalyzer:
    """AI 分析器"""

    SYSTEM_PROMPT = (
        "You are an expert news analyst. Analyze the provided news items and "
        "return a structured JSON analysis. You must respond with valid JSON only, "
        "no other text."
    )

    ANALYSIS_TEMPLATE = """\
Analyze the following {source_type} news items and provide insights.

News items:
{items}

Return a JSON object with the following fields:
- "core_trends": A summary of the main trends and hot topics (2-3 paragraphs)
- "signals": Notable anomalies, weak signals, or emerging patterns worth watching
- "outlook": Forward-looking analysis and strategic recommendations

Respond in Chinese (简体中文).
Return JSON: {{{{ "core_trends": "...", "signals": "...", "outlook": "..." }}}}"""

    def __init__(self, ai_config: Dict[str, Any]):
        """
        初始化 AI 分析器

        Args:
            ai_config: AI 模型配置（LiteLLM 格式）
        """
        self.client = AIClient(ai_config)

        # 验证配置
        valid, error = self.client.validate_config()
        if not valid:
            logger.warning("AI 配置警告: %s", error)

    def analyze(
        self,
        items: List[Dict],
        source_type: str = "hotlist",
    ) -> AIAnalysisResult:
        """
        执行 AI 分析

        Args:
            items: 新闻条目列表，每个条目至少包含 "title" 字段
            source_type: 来源类型（如 "hotlist"、"rss"）

        Returns:
            AIAnalysisResult: 分析结果
        """
        if not items:
            return AIAnalysisResult(
                success=False,
                error="无新闻条目可供分析",
            )

        # 格式化新闻内容
        items_text = self._format_items(items)

        # 构建提示词
        user_prompt = self.ANALYSIS_TEMPLATE.format(
            source_type=source_type,
            items=items_text,
        )

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # 打印分析开始信息
        model = self.client.model or "unknown"
        model_display = model.replace("/", "/\u200b") if model else "unknown"
        logger.info("开始分析 %d 条新闻 (来源: %s)", len(items), source_type)
        logger.info("模型: %s", model_display)

        try:
            response = self.client.chat(messages)

            if not response:
                return AIAnalysisResult(
                    success=False,
                    error="AI 返回空响应",
                )

            return self._parse_response(response)

        except RuntimeError as e:
            # litellm 未安装
            return AIAnalysisResult(
                success=False,
                error=str(e),
            )
        except Exception as e:
            logger.error("AI 分析失败: %s: %s", type(e).__name__, e)
            return AIAnalysisResult(
                success=False,
                error=f"AI 分析调用失败: {type(e).__name__}: {e}",
            )

    def _format_items(self, items: List[Dict]) -> str:
        """
        将新闻条目格式化为文本

        Args:
            items: 新闻条目列表

        Returns:
            str: 格式化后的文本
        """
        lines = []
        for i, item in enumerate(items):
            title = item.get("title", "无标题")
            source = item.get("source_name", item.get("source_id", ""))
            rank = item.get("rank", "")
            hot = item.get("hot_value", item.get("hot", ""))

            parts = [f"[{i+1}] {title}"]
            if source:
                parts.append(f"(来源: {source})")
            if rank:
                parts.append(f"(排名: {rank})")
            if hot:
                parts.append(f"(热度: {hot})")
            lines.append(" ".join(parts))

        return "\n".join(lines)

    def _parse_response(self, response: str) -> AIAnalysisResult:
        """
        解析 AI 分析响应

        Args:
            response: AI 返回的原始文本

        Returns:
            AIAnalysisResult
        """
        # 提取 JSON
        json_str = self._extract_json(response)

        if not json_str:
            # JSON 提取失败，将原始响应作为 core_trends
            logger.warning("无法提取 JSON，使用原始响应作为趋势总结")
            return AIAnalysisResult(
                core_trends=response[:2000] if response else "",
                raw_response=response,
                success=True,
            )

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error("JSON 解析错误: %s", e)
            return AIAnalysisResult(
                success=False,
                error=f"JSON 解析错误: {e}",
                raw_response=response,
            )

        if not isinstance(data, dict):
            logger.warning("AI 返回的不是 JSON 对象")
            return AIAnalysisResult(
                success=False,
                error="AI 返回格式错误：期望 JSON 对象",
                raw_response=response,
            )

        # 提取各字段
        core_trends = data.get("core_trends", data.get("core_trends_summary", ""))
        signals = data.get("signals", data.get("weak_signals", ""))
        outlook = data.get("outlook", data.get("outlook_strategy", data.get("strategy", "")))

        # 拼接缺失字段时的降级处理
        if not core_trends and isinstance(data, dict):
            # 尝试取第一个非空字符串字段
            for value in data.values():
                if isinstance(value, str) and len(value) > 50:
                    core_trends = value
                    break

        logger.info("分析完成")

        return AIAnalysisResult(
            core_trends=core_trends or "",
            signals=signals or "",
            outlook=outlook or "",
            raw_response=response,
            success=True,
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """
        从文本中提取 JSON 字符串

        支持:
        - 纯 JSON 数组/对象
        - ```json ... ``` 代码块
        - 混合文本中的 JSON
        """
        text = text.strip()

        # 尝试提取 ```json ... ``` 代码块
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 尝试直接解析整个文本
        if text.startswith("[") or text.startswith("{"):
            return text

        # 尝试查找第一个 [ 或 { 到最后一个 ] 或 }
        start_bracket = -1
        for char in ["[", "{"]:
            idx = text.find(char)
            if idx != -1 and (start_bracket == -1 or idx < start_bracket):
                start_bracket = idx

        if start_bracket != -1:
            end_bracket = max(text.rfind("]"), text.rfind("}"))
            if end_bracket > start_bracket:
                return text[start_bracket:end_bracket + 1]

        return ""
