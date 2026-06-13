# tests/test_router_instance.py
"""Tests for AIRouter instance-based client routing"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarvis.services.ai.router import AIRouter
from jarvis.services.ai.instance_config import ProviderInstance
from jarvis.services.ai.models import Provider
from jarvis.services.ai.providers import OllamaAdapter, OpenAIAdapter, AnthropicAdapter
from jarvis.services.ai.registry import ProviderRegistry

# Register providers (normally done by ChatEngine.__init__)
ProviderRegistry.register(Provider.OLLAMA, OllamaAdapter)
ProviderRegistry.register(Provider.OPENAI, OpenAIAdapter)
ProviderRegistry.register(Provider.ANTHROPIC, AnthropicAdapter)


class TestRouterInstanceRouting:
    def test_get_client_with_instance_uses_correct_base_url(self):
        """Two instances with same model but different base_url get different clients."""
        router = AIRouter()

        inst1 = ProviderInstance(
            id="inst-1", type="ollama", display_name="Inst1",
            base_url="http://localhost:11434", default_model="qwen3:4b",
        )
        inst2 = ProviderInstance(
            id="inst-2", type="ollama", display_name="Inst2",
            base_url="http://gpu-host:11434", default_model="qwen3:4b",
        )

        # Getting client for same model but different instance
        # The cache key includes instance.id so they should be separate
        client1 = router._get_client_with_instance(inst1, "qwen3:4b")
        client2 = router._get_client_with_instance(inst2, "qwen3:4b")

        # They should be different objects (different cache entries)
        assert client1 is not client2

        # Verify the base_url baked into each client
        assert client1.base_url == "http://localhost:11434"
        assert client2.base_url == "http://gpu-host:11434"

        router.clear_cache()

    def test_cache_key_includes_instance_id(self):
        """Same model, same base_url, but different instance id → different cache entries."""
        router = AIRouter()

        inst_a = ProviderInstance(
            id="cloud-1", type="ollama", display_name="Cloud1",
            base_url="http://shared:11434", default_model="qwen3:4b",
        )
        inst_b = ProviderInstance(
            id="cloud-2", type="ollama", display_name="Cloud2",
            base_url="http://shared:11434", default_model="qwen3:4b",
        )

        client_a = router._get_client_with_instance(inst_a, "qwen3:4b")
        client_b = router._get_client_with_instance(inst_b, "qwen3:4b")

        # Cache keys differ: "cloud-1:qwen3:4b" vs "cloud-2:qwen3:4b"
        assert client_a is not client_b

        router.clear_cache()

    def test_clear_cache_removes_all_clients(self):
        """clear_cache() empties the client cache."""
        router = AIRouter()
        inst = ProviderInstance(
            id="test", type="ollama", display_name="Test",
            base_url="http://localhost:11434", default_model="qwen3:4b",
        )
        client = router._get_client_with_instance(inst, "qwen3:4b")
        assert len(router._client_cache) == 1

        router.clear_cache()
        assert len(router._client_cache) == 0

    def test_get_client_with_instance_unknown_model_raises(self):
        """create_client_for_instance bypasses MODELS dict — unknown models no longer raise."""
        router = AIRouter()
        inst = ProviderInstance(
            id="test", type="ollama", display_name="Test",
            base_url="http://localhost:11434", default_model="nonexistent-model-xyz",
        )
        # Should NOT raise — create_client_for_instance accepts any model name
        client = router._get_client_with_instance(inst, "nonexistent-model-xyz")
        assert client is not None
        router.clear_cache()

    def test_close_clears_cache(self):
        """close() clears all clients and cache."""
        router = AIRouter()
        inst = ProviderInstance(
            id="close-test", type="ollama", display_name="CloseTest",
            base_url="http://localhost:11434", default_model="qwen3:4b",
        )
        router._get_client_with_instance(inst, "qwen3:4b")
        assert len(router._client_cache) == 1

        import asyncio
        asyncio.run(router.close())
        assert len(router._client_cache) == 0
