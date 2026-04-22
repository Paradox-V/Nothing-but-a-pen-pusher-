# coding=utf-8
"""
AI 智能筛选模块

通过 AI 对新闻进行标签分类：
对新闻标题按标签进行批量分类
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ai.client import AIClient

logger = logging.getLogger(__name__)


@dataclass
class AIFilterResult:
    """AI 筛选结果"""
    tags: List[Dict] = field(default_factory=list)
    # [{"tag": str, "description": str, "count": int, "items": [
    #     {"title": str, "source_id": str, "source_name": str,
    #      "url": str, "rank": int, "relevance_score": float}
    # ]}]
    total_matched: int = 0       # 匹配新闻总数
    total_processed: int = 0     # 处理新闻总数
    success: bool = False
    error: str = ""


class AIFilter:
    """AI 智能筛选器"""

    CLASSIFY_SYSTEM_PROMPT = (
        "You are a news classifier. Given a list of tags and news items, "
        "classify each item by assigning the most relevant tag and a relevance score.\n"
        "You must respond with valid JSON only, no other text."
    )

    CLASSIFY_USER_TEMPLATE = """\
Tags: {tags}

News items:
{items}

Return a JSON array where each element has:
- "id": the news item number (0-based)
- "tag": the best matching tag name from the tags list above
- "score": relevance score from 0.0 to 1.0

Only include items that match at least one tag with score >= 0.3.
Return JSON: [{{"id": 0, "tag": "tag_name", "score": 0.8}}, ...]"""

    def __init__(self, ai_config: Dict[str, Any]):
        """
        初始化 AI 筛选器

        Args:
            ai_config: AI 模型配置（LiteLLM 格式）
        """
        self.client = AIClient(ai_config)

        # 验证配置
        valid, error = self.client.validate_config()
        if not valid:
            logger.warning("AI筛选配置警告: %s", error)

    def classify_batch(
        self,
        items: List[Dict],
        tags: List[Dict],
    ) -> AIFilterResult:
        """
        对新闻条目进行批量分类

        Args:
            items: 新闻条目列表，每个条目至少包含 "title" 字段
            tags: 标签列表，格式: [{"tag": str, "description": str}, ...]

        Returns:
            AIFilterResult: 筛选结果
        """
        if not items:
            return AIFilterResult(
                total_processed=0,
                total_matched=0,
                success=True,
            )

        if not tags:
            return AIFilterResult(
                total_processed=len(items),
                total_matched=0,
                success=True,
            )

        # 格式化标签列表
        tag_lines = []
        for t in tags:
            tag_name = t.get("tag", "")
            tag_desc = t.get("description", "")
            if tag_desc:
                tag_lines.append(f"- {tag_name}: {tag_desc}")
            else:
                tag_lines.append(f"- {tag_name}")
        tags_text = "\n".join(tag_lines)

        # 格式化新闻条目（带编号）
        item_lines = []
        for i, item in enumerate(items):
            title = item.get("title", "")
            source = item.get("source_name", item.get("source_id", ""))
            if source:
                item_lines.append(f"[{i}] {title} (来源: {source})")
            else:
                item_lines.append(f"[{i}] {title}")
        items_text = "\n".join(item_lines)

        # 构建提示词
        user_prompt = self.CLASSIFY_USER_TEMPLATE.format(
            tags=tags_text,
            items=items_text,
        )

        messages = [
            {"role": "system", "content": self.CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        logger.info("开始分类 %d 条新闻，使用 %d 个标签", len(items), len(tags))

        try:
            response = self.client.chat(messages)
            classifications = self._parse_classify_response(response)

            if classifications is None:
                return AIFilterResult(
                    total_processed=len(items),
                    total_matched=0,
                    success=False,
                    error="AI 返回的 JSON 解析失败",
                )

            # 将分类结果映射回原始条目
            return self._build_result(items, tags, classifications)

        except RuntimeError as e:
            # litellm 未安装
            return AIFilterResult(
                total_processed=len(items),
                success=False,
                error=str(e),
            )
        except Exception as e:
            logger.error("AI筛选分类失败: %s: %s", type(e).__name__, e)
            return AIFilterResult(
                total_processed=len(items),
                success=False,
                error=f"AI 分类调用失败: {type(e).__name__}: {e}",
            )

    def _parse_classify_response(self, response: str) -> List[Dict]:
        """
        解析 AI 分类响应

        Args:
            response: AI 返回的原始文本

        Returns:
            分类结果列表，解析失败返回 None
        """
        # 尝试提取 JSON
        json_str = self._extract_json(response)
        if not json_str:
            logger.warning("无法从AI筛选响应中提取 JSON")
            return None

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error("AI筛选 JSON 解析错误: %s", e)
            return None

        if not isinstance(data, list):
            logger.warning("AI筛选返回的不是数组")
            return None

        # 验证每条结果
        valid = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if "id" not in item or "tag" not in item or "score" not in item:
                continue
            try:
                item["id"] = int(item["id"])
                item["score"] = float(item["score"])
            except (ValueError, TypeError):
                continue
            valid.append(item)

        logger.info("解析到 %d 条有效分类结果", len(valid))
        return valid

    def _build_result(
        self,
        items: List[Dict],
        tags: List[Dict],
        classifications: List[Dict],
    ) -> AIFilterResult:
        """
        将分类结果组装为 AIFilterResult

        Args:
            items: 原始新闻条目
            tags: 标签列表
            classifications: AI 返回的分类结果

        Returns:
            AIFilterResult
        """
        # 建立标签索引
        tag_map = {t["tag"]: t for t in tags if "tag" in t}

        # 按 tag 分组
        grouped: Dict[str, List[Dict]] = {}
        for cls in classifications:
            item_id = cls["id"]
            tag_name = cls["tag"]
            score = cls["score"]

            # 跳过无效索引
            if item_id < 0 or item_id >= len(items):
                continue

            # 跳过低分项
            if score < 0.3:
                continue

            if tag_name not in grouped:
                grouped[tag_name] = []

            # 构造匹配条目
            original = items[item_id]
            matched_item = dict(original)
            matched_item["relevance_score"] = score
            grouped[tag_name].append(matched_item)

        # 组装结果
        result_tags = []
        total_matched = 0
        for tag_name, matched_items in grouped.items():
            tag_info = tag_map.get(tag_name, {"tag": tag_name})
            result_tags.append({
                "tag": tag_name,
                "description": tag_info.get("description", ""),
                "count": len(matched_items),
                "items": matched_items,
            })
            total_matched += len(matched_items)

        logger.info("分类完成: %d 个标签命中，共 %d 条新闻", len(result_tags), total_matched)

        return AIFilterResult(
            tags=result_tags,
            total_matched=total_matched,
            total_processed=len(items),
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
