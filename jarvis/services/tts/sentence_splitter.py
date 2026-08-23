# jarvis/services/tts/sentence_splitter.py
"""中文/英文句切分 — 用于流式 chat 时按句触发 TTS 合成。

从 voice-clone-demo/llm_service.py:_find_split 改造而来，
原版返回单次切分索引（用于累积 buffer），这里改成 generator 持续 yield。
"""
import re
from typing import Iterator, Optional

# 句末标点：中文全角 + 英文半角 + 双标点
_SENT_END = re.compile(r"([。！？!?]+|[.!?]{2,})")
# 软切点：逗号、分号
_SOFT_END = re.compile(r"([，；,;])")


def _find_split(text: str, min_chars: int, max_chars: int) -> Optional[int]:
    """找最早的可切分位置（优先级：句末 > 软切点 > 长度阈值）。"""
    m = _SENT_END.search(text)
    if m and m.end() >= min_chars:
        return m.end()
    if len(text) >= max_chars:
        sm = _SOFT_END.search(text, min_chars)
        if sm:
            return sm.end()
        # 没有软切点，强制按 max_chars 切
        return max_chars
    return None


def split_by_punctuation(
    text: str,
    min_chars: int = 6,
    max_chars: int = 25,
) -> Iterator[str]:
    """按标点持续切句，yield 非空句子。

    例:
        "你好。今天天气真好，我想去公园。" →
            "你好。" / "今天天气真好，我想去公园。"
    """
    if not text:
        return
    while text:
        idx = _find_split(text, min_chars, max_chars)
        if idx is None:
            # 剩余不足阈值，整段作为最后一句
            stripped = text.strip()
            if stripped:
                yield stripped
            return
        sentence = text[:idx].strip()
        if sentence:
            yield sentence
        text = text[idx:]