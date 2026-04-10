"""
文案创作模块 - 文案框架生成与迭代

简化自 ms-DYP 的 framework_generator.py，使用 DeepSeek + 信源汇总数据
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class FrameworkStatus(str, Enum):
    DRAFT = "draft"
    EDITING = "editing"
    CONFIRMED = "confirmed"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Framework:
    """文案框架"""
    id: str
    title: str
    requirements: str = ""
    industry: str = ""
    keyword: str = ""
    article_structure: str = ""       # 50 字结构规划
    writing_approach: str = ""        # 200 字切入点+维度+观点
    reference_material: str = ""      # 参考素材摘要
    status: FrameworkStatus = FrameworkStatus.DRAFT
    chat_history: list[dict] = field(default_factory=list)
    final_article: str = ""
    images: list[str] = field(default_factory=list)
    round: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "requirements": self.requirements,
            "industry": self.industry,
            "keyword": self.keyword,
            "article_structure": self.article_structure,
            "writing_approach": self.writing_approach,
            "reference_material": self.reference_material[:500],
            "status": self.status.value,
            "chat_history": self.chat_history,
            "final_article": self.final_article[:200] if self.final_article else "",
            "images": self.images,
            "round": self.round,
        }

    def to_db_dict(self) -> dict:
        """完整字典（用于持久化，不含截断）"""
        return {
            "id": self.id,
            "title": self.title,
            "requirements": self.requirements,
            "industry": self.industry,
            "keyword": self.keyword,
            "article_structure": self.article_structure,
            "writing_approach": self.writing_approach,
            "reference_material": self.reference_material,
            "status": self.status.value,
            "chat_history": self.chat_history,
            "final_article": self.final_article,
            "images": self.images,
            "round": self.round,
        }

    @classmethod
    def from_db_dict(cls, d: dict) -> "Framework":
        """从数据库字典恢复 Framework 对象"""
        return cls(
            id=d["id"],
            title=d["title"],
            requirements=d.get("requirements", ""),
            industry=d.get("industry", ""),
            keyword=d.get("keyword", ""),
            article_structure=d.get("article_structure", ""),
            writing_approach=d.get("writing_approach", ""),
            reference_material=d.get("reference_material", ""),
            status=FrameworkStatus(d.get("status", "draft")),
            chat_history=d.get("chat_history", []),
            final_article=d.get("final_article", ""),
            images=d.get("images", []),
            round=d.get("round", 0),
        )


# ── 持久化存储 ──────────────────────────────────────────────────

from modules.creator.db import CreatorDB

_db = CreatorDB()


def get_framework(fw_id: str) -> Framework | None:
    d = _db.get_framework(fw_id)
    return Framework.from_db_dict(d) if d else None


def store_framework(fw: Framework) -> None:
    _db.save_framework(fw.to_db_dict())


# ── AI 调用封装 ───────────────────────────────────────────────

def _call_llm(messages: list[dict], ai_config: dict | None = None) -> str:
    """调用 DeepSeek LLM"""
    from ai.client import AIClient

    config = ai_config or _default_ai_config()
    client = AIClient(config)
    content = client.chat(messages=messages, temperature=0.8, max_tokens=4000)
    return content or ""


def _default_ai_config() -> dict:
    from ai.config import get_ai_config
    return get_ai_config()


def _extract_json(content: str) -> dict:
    """从 LLM 响应中提取 JSON"""
    # 直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # ```json ... ``` 块
    for match in re.findall(r'```(?:json)?\s*([\s\S]*?)\s*```', content):
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    # 第一个 { 到最后一个 }
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError("无法从响应中提取 JSON")


# ── 核心流程 ──────────────────────────────────────────────────

def create_framework(
    title: str,
    requirements: str = "",
    industry: str = "",
    keyword: str = "",
    ai_config: dict | None = None,
) -> Framework:
    """
    创建文案框架：
    1. 从信源汇总数据中检索参考素材
    2. LLM 生成 article_structure + writing_approach
    """
    fw_id = uuid.uuid4().hex[:12]
    fw = Framework(
        id=fw_id,
        title=title,
        requirements=requirements,
        industry=industry,
        keyword=keyword,
    )

    # 检索参考素材
    reference = _search_references(title, industry, keyword)
    fw.reference_material = reference

    # 构建 prompt
    core_theme = ""
    if industry or keyword:
        core_theme = f"\n【行业+关键词】\n{industry} - {keyword}"

    prompt = f"""你是一个专业的内容策划师，擅长为公众号文章设计内容框架。

请根据以下信息，设计一个简化的内容框架：

【文章标题】
{title}
{core_theme}

【写作要求】
{requirements or "无特殊要求"}

【参考素材】
{reference or "无参考素材"}

【框架结构要求】
请生成一个简化框架，包含以下内容：
1. 文章结构：50字左右的结构规划（与具体内容无关的高层次结构描述，如"引言→现状分析→问题剖析→解决方案→总结展望"）
2. 切入点+创作维度+核心观点：200字左右，概述文章的切入角度、创作维度和核心观点

请严格按照以下JSON格式输出框架（不要输出其他内容）：
```json
{{
    "article_structure": "文章结构规划，50字左右",
    "writing_approach": "切入点+创作维度+核心观点，200字左右"
}}
```"""

    messages = [
        {"role": "system", "content": "你是一个专业的内容策划师。请严格按照JSON格式输出。"},
        {"role": "user", "content": prompt},
    ]

    try:
        content = _call_llm(messages, ai_config)
        data = _extract_json(content)
        fw.article_structure = data.get("article_structure", "")
        fw.writing_approach = data.get("writing_approach", "")
        fw.status = FrameworkStatus.DRAFT
    except (ConnectionError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        logger.error("框架生成失败: %s", e)
        fw.article_structure = "引言→现状分析→问题剖析→解决方案→总结展望"
        fw.writing_approach = "从行业现状切入，结合关键词深入分析问题本质，提出切实可行的解决方案。"
        fw.status = FrameworkStatus.DRAFT

    fw.chat_history.append({"role": "assistant", "content": f"框架已生成。\n\n**文章结构：** {fw.article_structure}\n\n**切入点+创作维度：** {fw.writing_approach}"})

    store_framework(fw)
    return fw


def update_framework(
    fw: Framework,
    message: str,
    regenerate: bool = False,
    ai_config: dict | None = None,
) -> Framework:
    """对话调整框架"""
    fw.round += 1
    fw.chat_history.append({"role": "user", "content": message})

    if regenerate:
        # 整体重生成
        prompt = f"""你是一个专业的内容策划师，需要根据用户的反馈完全重新设计文章框架。

【文章标题】{fw.title}
【行业+关键词】{fw.industry} - {fw.keyword}
【写作要求】{fw.requirements or "无特殊要求"}
【参考素材】{fw.reference_material[:500] or "无"}
【用户重构请求】{message}

请重新设计框架，输出JSON：
```json
{{
    "article_structure": "新的文章结构，50字左右",
    "writing_approach": "新的切入点+创作维度+核心观点，200字左右"
}}
```"""
    else:
        # 定向修改
        prompt = f"""你是一个专业的内容编辑，需要根据用户反馈修改文章框架。

【当前框架】
标题: {fw.title}
文章结构: {fw.article_structure}
切入点+创作维度: {fw.writing_approach}

【用户反馈】
{message}

请输出修改后的JSON：
```json
{{
    "article_structure": "修改后的文章结构",
    "writing_approach": "修改后的切入点+创作维度+核心观点"
}}
```"""

    messages = [
        {"role": "system", "content": "你是专业内容编辑。严格按照JSON格式输出。"},
        {"role": "user", "content": prompt},
    ]

    try:
        content = _call_llm(messages, ai_config)
        data = _extract_json(content)
        if "article_structure" in data:
            fw.article_structure = data["article_structure"]
        if "writing_approach" in data:
            fw.writing_approach = data["writing_approach"]
        fw.status = FrameworkStatus.EDITING
        fw.chat_history.append({"role": "assistant", "content": f"框架已更新。\n\n**文章结构：** {fw.article_structure}\n\n**切入点+创作维度：** {fw.writing_approach}"})
    except (ConnectionError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        logger.error("框架更新失败: %s", e)

    store_framework(fw)
    return fw


def confirm_framework(fw: Framework) -> Framework:
    """确认框架"""
    fw.status = FrameworkStatus.CONFIRMED
    fw.chat_history.append({"role": "assistant", "content": "框架已确认，可以开始生成文章。"})
    store_framework(fw)
    return fw


def _search_references(title: str, industry: str, keyword: str) -> str:
    """从信源汇总数据中检索参考素材"""
    query = f"{industry} {keyword} {title}"
    try:
        from modules.topic.service import semantic_search
        results = semantic_search(query, top_k=3)
        if results:
            refs = []
            for i, r in enumerate(results[:3], 1):
                refs.append(f"【参考{i}】{r.get('title', '')}\n{(r.get('content') or '')[:200]}")
            return "\n\n".join(refs)
    except (ImportError, ConnectionError, RuntimeError, ValueError) as e:
        logger.warning("参考素材检索失败: %s", e)
    return ""
