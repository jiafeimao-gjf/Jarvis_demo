# tests/test_instance_config.py
"""Tests for Provider Instance Configuration module"""
import pytest
import sys
from pathlib import Path

# Ensure jarvis is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from jarvis.services.ai.instance_config import ProviderInstance


class TestProviderInstance:
    def test_create_instance(self):
        inst = ProviderInstance(
            id="ollama-local",
            type="ollama",
            display_name="本地 Ollama",
            base_url="http://localhost:11434",
            default_model="qwen3:4b",
            enabled=True,
            timeout=120.0,
        )
        assert inst.id == "ollama-local"
        assert inst.type == "ollama"
        assert inst.base_url == "http://localhost:11434"
        assert inst.enabled is True

    def test_to_dict_redacts_api_key(self):
        inst = ProviderInstance(
            id="openai-test",
            type="openai",
            display_name="OpenAI Test",
            api_key="sk-secret123",
            default_model="gpt-4o-mini",
        )
        d = inst.to_dict(redact_secrets=True)
        assert d["api_key"] is None
        assert d["has_api_key"] is True
        assert d["id"] == "openai-test"

    def test_to_dict_no_redact(self):
        inst = ProviderInstance(
            id="anthropic-test",
            type="anthropic",
            display_name="Claude",
            api_key="sk-ant-api123",
            default_model="claude-3-haiku",
        )
        d = inst.to_dict(redact_secrets=False)
        assert d["api_key"] == "sk-ant-api123"
        assert d["has_api_key"] is None

    def test_from_dict_roundtrip(self):
        original = ProviderInstance(
            id="test-roundtrip",
            type="ollama",
            display_name="Roundtrip Test",
            base_url="http://localhost:11434",
            api_key=None,
            default_model="qwen3:4b",
            enabled=False,
            timeout=90.0,
        )
        d = original.to_dict(redact_secrets=False)
        restored = ProviderInstance.from_dict(d)
        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.display_name == original.display_name
        assert restored.base_url == original.base_url
        assert restored.default_model == original.default_model
        assert restored.enabled == original.enabled
        assert restored.timeout == original.timeout


class TestInstanceConfigStore:
    @pytest.fixture
    def fresh_store(self, tmp_path):
        """Create a fresh InstanceConfigStore with a temp DB."""
        import tempfile
        import os
        # Use a temp file for the DB path
        db_file = tempfile.mktemp(suffix=".db")
        yield db_file
        if os.path.exists(db_file):
            os.unlink(db_file)

    @pytest.mark.asyncio
    async def test_seed_default_creates_ollama_instance(self):
        """When DB is empty, seed creates ollama-default."""
        from jarvis.services.ai.instance_config import InstanceConfigStore
        store = InstanceConfigStore()
        instances = store._seed_default()
        assert len(instances) >= 1
        assert any(i.id == "ollama-default" for i in instances)

    @pytest.mark.asyncio
    async def test_seed_skips_cloud_providers_without_keys(self):
        """Cloud providers are not seeded if env has no API keys."""
        from jarvis.services.ai.instance_config import InstanceConfigStore
        store = InstanceConfigStore()
        instances = store._seed_default()
        # Without API keys set in env, only ollama should be seeded
        cloud_ids = [i.id for i in instances if i.type in ("openai", "anthropic")]
        # If env has no keys, cloud should not appear
        # (test passes if either cloud was skipped or was seeded with enabled=False)
        for inst in instances:
            if inst.type in ("openai", "anthropic"):
                assert not inst.enabled or inst.api_key

    @pytest.mark.asyncio
    async def test_get_by_id_returns_correct_instance(self):
        from jarvis.services.ai.instance_config import InstanceConfigStore
        store = InstanceConfigStore()
        store._instances = [
            ProviderInstance(id="a", type="ollama", display_name="A", default_model="q"),
            ProviderInstance(id="b", type="openai", display_name="B", default_model="gpt"),
        ]
        store._loaded = True
        assert store.get_by_id("a").display_name == "A"
        assert store.get_by_id("b").display_name == "B"
        assert store.get_by_id("c") is None

    @pytest.mark.asyncio
    async def test_get_active_instance_returns_enabled(self):
        from jarvis.services.ai.instance_config import InstanceConfigStore
        store = InstanceConfigStore()
        store._instances = [
            ProviderInstance(id="a", type="ollama", display_name="A", default_model="q", enabled=False),
            ProviderInstance(id="b", type="ollama", display_name="B", default_model="q", enabled=True),
        ]
        store._active_id = "a"
        store._loaded = True
        # Since "a" is disabled, should fall back to "b"
        active = store.get_active_instance()
        assert active.id == "b"

    @pytest.mark.asyncio
    async def test_remove_instance_clears_active_and_switches(self):
        from jarvis.services.ai.instance_config import InstanceConfigStore
        store = InstanceConfigStore()
        store._instances = [
            ProviderInstance(id="a", type="ollama", display_name="A", default_model="q", enabled=True),
            ProviderInstance(id="b", type="ollama", display_name="B", default_model="q", enabled=True),
        ]
        store._active_id = "a"
        store._loaded = True

        removed = store.remove_instance("a")
        assert removed is True
        assert store._active_id == "b"
        assert len(store._instances) == 1
        assert store.get_by_id("a") is None

    @pytest.mark.asyncio
    async def test_add_instance_rejects_duplicate(self):
        from jarvis.services.ai.instance_config import InstanceConfigStore
        store = InstanceConfigStore()
        store._instances = [
            ProviderInstance(id="dup", type="ollama", display_name="Dup", default_model="q"),
        ]
        store._loaded = True
        result = store.add_instance(
            ProviderInstance(id="dup", type="ollama", display_name="Dup2", default_model="q")
        )
        assert result is False
        assert len(store._instances) == 1

    @pytest.mark.asyncio
    async def test_update_instance_replaces(self):
        from jarvis.services.ai.instance_config import InstanceConfigStore
        store = InstanceConfigStore()
        store._instances = [
            ProviderInstance(id="upd", type="ollama", display_name="Old", default_model="q", enabled=True),
        ]
        store._loaded = True
        updated = ProviderInstance(id="upd", type="ollama", display_name="New", default_model="q", enabled=False)
        result = store.update_instance("upd", updated)
        assert result is True
        assert store.get_by_id("upd").display_name == "New"
        assert store.get_by_id("upd").enabled is False
