# jarvis/core/chat_engine.py
"""对话引擎 - 核心业务逻辑"""
from typing import Optional
from jarvis.core.entities import Message, Conversation
from jarvis.core.memory_store import memory_store
from jarvis.services.ai import AIRouter, AIConfig, ProviderRegistry
from jarvis.services.ai.providers import OllamaAdapter, OpenAIAdapter, AnthropicAdapter
from jarvis.services.ai.models import Provider
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class ChatEngine:
    """对话引擎 - 管理对话上下文和 LLM 调用"""

    def __init__(self):
        # Register providers
        ProviderRegistry.register(Provider.OLLAMA, OllamaAdapter)
        ProviderRegistry.register(Provider.OPENAI, OpenAIAdapter)
        ProviderRegistry.register(Provider.ANTHROPIC, AnthropicAdapter)

        # Initialize AI config
        self.ai_config = AIConfig()
        self.router = AIRouter(self.ai_config)
        self.memory = memory_store
        self.current_conversation: Optional[Conversation] = None
        self.system_prompt = """你叫贾维斯（JARVIS），是一个智能助手。
你有以下能力：
- 语音对话和文字对话
- 视觉理解（看图分析）
- 任务自动化执行
- 个人记忆管理
- 系统控制和自动化

请用中文回答，保持简洁、专业且有帮助。"""

    async def chat(
        self,
        user_input: str,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None,
        stream: bool = False  # Default to non-stream for simpler response
    ) -> str:
        """处理对话"""
        # 1. 获取或创建对话上下文
        if conversation_id:
            conv_data = await self.memory.get_conversation(conversation_id)
            if conv_data:
                self.current_conversation = Conversation(
                    conversation_id=conversation_id,
                    user_id=conv_data.get("user_id", ""),
                    messages=[Message(**m) for m in conv_data.get("messages", [])],
                    context=conv_data.get("context", {})
                )
            else:
                self.current_conversation = Conversation(conversation_id=conversation_id)
        else:
            self.current_conversation = Conversation()

        # 2. 添加用户消息
        self.current_conversation.add_message("user", user_input)

        # 3. 检索相关记忆
        memories = await self.memory.retrieve(user_input, top_k=3)
        context_prompt = ""
        if memories:
            context_prompt = "\n相关记忆：\n" + "\n".join(
                [f"- {m['content']}" for m in memories]
            )

        # 4. 构建消息历史
        messages = [
            {"role": "system", "content": self.system_prompt + context_prompt}
        ]
        for msg in self.current_conversation.get_history(limit=10):
            messages.append({"role": msg.role, "content": msg.content})

        # 5. 调用 LLM
        response = await self.router.chat(
            messages,
            model=model,
            stream=False
        )

        # 6. 添加助手消息
        self.current_conversation.add_message("assistant", response.content)

        # 7. 保存对话历史
        await self.memory.save_conversation(
            self.current_conversation.conversation_id,
            self.current_conversation.user_id,
            [msg.to_dict() for msg in self.current_conversation.messages],
            self.current_conversation.context
        )

        # 8. 保存相关记忆（如果是有意义的信息）
        if len(user_input) > 10 and "记住" in user_input:
            key = user_input[:50].strip()
            await self.memory.save(key, user_input)

        return response.content

    async def stream_chat(
        self,
        user_input: str,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None
    ):
        """流式对话"""
        messages = [
            {"role": "system", "content": self.system_prompt}
        ]
        if conversation_id:
            conv_data = await self.memory.get_conversation(conversation_id)
            if conv_data:
                messages.extend([
                    {"role": m["role"], "content": m["content"]}
                    for m in conv_data.get("messages", [])[-10:]
                ])

        messages.append({"role": "user", "content": user_input})

        async for token in self.router.chat_stream(messages, model=model):
            yield token

    async def list_models(self) -> list[dict]:
        """List available models from all providers"""
        return await self.router.list_models()

    def to_dict(self) -> dict:
        """导出状态"""
        return {
            "current_conversation": {
                "conversation_id": self.current_conversation.conversation_id if self.current_conversation else None,
                "messages_count": len(self.current_conversation.messages) if self.current_conversation else 0
            }
        }