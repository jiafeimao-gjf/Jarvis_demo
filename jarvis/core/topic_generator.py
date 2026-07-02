# jarvis/core/topic_generator.py
"""Auto-generate a short Chinese topic from the first user message."""
from __future__ import annotations

import asyncio
from typing import Optional

from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

_TOPIC_SYSTEM_PROMPT = (
    "你是一个对话主题生成器。根据用户的第一条消息，"
    "生成一个 4-12 个字的简洁中文主题。"
    "只输出主题文字本身，不要标点符号、引号、解释或前缀。"
)


def _fallback_topic(user_input: str) -> str:
    """Fallback when LLM fails: use first 12 chars of user input."""
    cleaned = (user_input or "").strip().replace("\n", " ")
    return cleaned[:12] if cleaned else "新对话"


def _clean_topic(raw: str) -> str:
    """Strip whitespace, quotes, prefixes from the LLM response."""
    if not raw:
        return ""
    s = raw.strip()
    # Remove surrounding quotes (English or Chinese)
    for q in ('"', "'", '"', '"', ''', ''', '「', '」', '『', '』', '《', '》'):
        s = s.strip(q)
    # Remove common prefixes the LLM may add
    for prefix in ("主题：", "主题:", "主题", "Title:", "Title：", "主题是", "本对话主题是", "对话主题："):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
    # Strip leading/trailing punctuation
    s = s.strip("：:，,。.；;、!?？")
    s = s.strip()
    return s[:60]


async def generate_topic(router, user_input: str,
                         model: Optional[str] = None,
                         instance=None,
                         timeout: float = 5.0) -> str:
    """Generate a 4-12 char Chinese topic for a conversation.

    Falls back to the first 12 chars of user_input on any failure.
    """
    if not user_input or not router:
        return _fallback_topic(user_input or "")

    messages = [
        {"role": "system", "content": _TOPIC_SYSTEM_PROMPT},
        {"role": "user", "content": user_input[:500]},
    ]

    try:
        resp = await asyncio.wait_for(
            router.chat(messages, model=model, instance=instance,
                        max_tokens=40, temperature=0.3),
            timeout=timeout,
        )
        text = resp.content if resp else ""
        cleaned = _clean_topic(text)
        if cleaned:
            return cleaned
    except asyncio.TimeoutError:
        logger.warning(f"[topic] generation timeout ({timeout}s)")
    except Exception as e:
        logger.warning(f"[topic] generation failed: {type(e).__name__}: {e}")

    return _fallback_topic(user_input)
