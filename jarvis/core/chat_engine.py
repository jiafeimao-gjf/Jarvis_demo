# jarvis/core/chat_engine.py
"""对话引擎 - 核心业务逻辑"""
from pathlib import Path
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
        self.work_folder: str = str(Path.cwd())

        # 工具列表定义
        self.available_tools = """## 可用工具

### 1. 文件操作 (tool: file)
执行文件读写编辑删除等操作。

| 操作 | 参数 | 说明 |
|------|------|------|
| read | path | 读取文件内容 |
| write | path, content | 写入文件 |
| edit | path, old_content, new_content | 修改文件 |
| delete | path | 删除文件/目录 |
| list | path | 列出目录文件 |
| mkdir | path | 创建目录 |
| exists | path | 检查文件是否存在 |
| set_work_folder | folder | 设置工作目录 |
| get_work_folder | - | 获取当前工作目录 |

### 2. 浏览器自动化 (tool: browser)
使用 Playwright 执行浏览器操作。

### 3. 桌面控制 (tool: desktop)
使用 pyautogui 执行桌面自动化操作。

### 4. API 调用 (tool: api)
发送 HTTP 请求。

调用示例：
```
POST /api/execute/file
{"action": "read", "path": "file.txt"}
```

## 工作目录
当前工作目录: {work_folder}

请用中文回答，保持简洁、专业且有帮助。如果需要执行操作，请明确说明将使用哪个工具。"""

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        return self.available_tools.replace("{work_folder}", self.work_folder)

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
            {"role": "system", "content": self._build_system_prompt() + context_prompt}
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
            {"role": "system", "content": self._build_system_prompt()}
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

    def set_work_folder(self, folder: str):
        """设置工作目录"""
        self.work_folder = folder
        logger.info(f"Work folder set to: {folder}")

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