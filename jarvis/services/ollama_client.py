# jarvis/services/ollama_client.py
"""Ollama API 客户端封装 - Factory Pattern + Strategy Pattern"""
import asyncio
import json
import httpx
from abc import ABC, abstractmethod
from typing import Optional, AsyncIterator, Any
from dataclasses import dataclass

from jarvis.config import settings
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AIResponse:
    """AI 响应数据结构"""
    content: str
    model: str
    done: bool = True
    context: Optional[list[int]] = None
    raw: Optional[dict] = None


class AIClient(ABC):
    """AI 客户端抽象接口（Strategy Pattern）"""

    @abstractmethod
    async def generate(self, prompt: str, stream: bool = True) -> AIResponse:
        """生成文本"""
        pass

    @abstractmethod
    async def chat(self, messages: list[dict], stream: bool = True) -> AIResponse:
        """对话"""
        pass

    @abstractmethod
    async def vision_analyze(self, image_data: bytes, prompt: str) -> str:
        """视觉分析"""
        pass


class OllamaClient(AIClient):
    """Ollama API 客户端"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        vision_model: Optional[str] = None
    ):
        self.base_url = base_url or settings.ai.ollama.base_url
        self.model = model or settings.ai.ollama.model
        self.vision_model = vision_model or settings.ai.ollama.vision_model
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """懒加载 HTTP 客户端"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(60.0)
            )
        return self._client

    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate(
        self,
        prompt: str,
        stream: bool = True,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048
    ) -> AIResponse:
        """生成文本"""
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": stream,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            if system:
                payload["system"] = system

            response = await self.client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()

            return AIResponse(
                content=data.get("response", ""),
                model=self.model,
                done=data.get("done", True),
                context=data.get("context"),
                raw=data
            )
        except httpx.HTTPError as e:
            logger.error(f"Ollama generate error: {e}")
            return AIResponse(content=f"Error: {str(e)}", model=self.model)

    async def chat(
        self,
        messages: list[dict],
        stream: bool = True,
        temperature: float = 0.7,
        max_tokens: int = 2048
    ) -> AIResponse:
        """对话"""
        for attempt in range(3):
            try:
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": stream,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens
                    }
                }

                response = await self.client.post("/api/chat", json=payload)

                if response.status_code == 404:
                    logger.warning(f"Model {self.model} not found, attempt {attempt + 1}/3")
                    if attempt == 2:
                        return AIResponse(
                            content=f"Error: Model {self.model} not found. Please check Ollama model list.",
                            model=self.model
                        )
                    await asyncio.sleep(1)
                    continue

                response.raise_for_status()
                data = response.json()

                return AIResponse(
                    content=data.get("message", {}).get("content", ""),
                    model=self.model,
                    done=data.get("done", True),
                    raw=data
                )
            except httpx.HTTPError as e:
                logger.error(f"Ollama chat error (attempt {attempt + 1}/3): {e}")
                if attempt == 2:
                    return AIResponse(content=f"Error: {str(e)}", model=self.model)
                await asyncio.sleep(1)
        return AIResponse(content="Error: Max retries exceeded", model=self.model)

    async def vision_analyze(self, image_data: bytes, prompt: str) -> str:
        """视觉分析（图片理解）"""
        try:
            import base64
            image_base64 = base64.b64encode(image_data).decode()

            payload = {
                "model": self.vision_model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [image_base64]
                    }
                ],
                "stream": False
            }

            response = await self.client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

            return data.get("message", {}).get("content", "")
        except httpx.HTTPError as e:
            logger.error(f"Ollama vision error: {e}")
            return f"Error: {str(e)}"

    async def chat_stream(
        self,
        messages: list[dict]
    ) -> AsyncIterator[str]:
        """流式对话"""
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": True
            }

            async with self.client.stream("POST", "/api/chat", json=payload) as response:
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
        except httpx.HTTPError as e:
            logger.error(f"Ollama chat stream error: {e}")
            yield f"Error: {str(e)}"

    async def generate_stream(
        self,
        prompt: str,
        system: Optional[str] = None
    ) -> AsyncIterator[str]:
        """流式生成文本"""
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": True
            }
            if system:
                payload["system"] = system

            async with self.client.stream("POST", "/api/generate", json=payload) as response:
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        yield data.get("response", "")
                        if data.get("done"):
                            break
        except httpx.HTTPError as e:
            logger.error(f"Ollama stream error: {e}")
            yield f"Error: {str(e)}"

    async def check_health(self) -> bool:
        """检查 Ollama 服务健康状态"""
        try:
            response = await self.client.get("/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False

    async def list_models(self) -> list[dict]:
        """列出可用模型"""
        try:
            response = await self.client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            return data.get("models", [])
        except httpx.HTTPError as e:
            logger.error(f"Failed to list models: {e}")
            return []


class AIClientFactory:
    """AI 客户端工厂（Factory Pattern）"""

    _clients: dict[str, type[AIClient]] = {
        "ollama": OllamaClient,
        # 可扩展其他客户端
        # "claude": ClaudeClient,
        # "openai": OpenAIClient,
    }

    @classmethod
    def create_client(cls, provider: str = "ollama", **kwargs) -> AIClient:
        """创建 AI 客户端"""
        client_class = cls._clients.get(provider)
        if not client_class:
            raise ValueError(f"Unknown AI provider: {provider}")
        return client_class(**kwargs)

    @classmethod
    def register_client(cls, provider: str, client_class: type[AIClient]):
        """注册新的 AI 客户端"""
        cls._clients[provider] = client_class


# 全局单例
ollama_client = OllamaClient()