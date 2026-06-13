# jarvis/services/ai/instance_config.py
"""Provider Instance Configuration — multi-instance support"""
from dataclasses import dataclass
from typing import Optional, List
import json

from jarvis.config import settings
from jarvis.core.memory_store import memory_store
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProviderInstance:
    """A configured instance of an AI provider (one of many per type)"""
    id: str                          # unique slug, e.g. "ollama-local"
    type: str                        # "ollama" | "openai" | "anthropic"
    display_name: str                # UI display name, e.g. "本地 Ollama"
    base_url: Optional[str] = None   # ollama: required; openai/anthropic: optional
    api_key: Optional[str] = None    # openai/anthropic: required; ollama: unused
    default_model: str = ""          # default model for this instance
    enabled: bool = True
    timeout: float = 60.0

    def to_dict(self, redact_secrets: bool = True) -> dict:
        d = {
            "id": self.id,
            "type": self.type,
            "display_name": self.display_name,
            "base_url": self.base_url,
            "api_key": self.api_key if not redact_secrets else None,
            "has_api_key": bool(self.api_key) if redact_secrets else None,
            "default_model": self.default_model,
            "enabled": self.enabled,
            "timeout": self.timeout,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProviderInstance":
        d = dict(d)
        d.pop("has_api_key", None)
        return cls(**d)


class InstanceConfigStore:
    """
    In-memory cache + SQLite persistence for provider instances.
    Lives alongside the existing memory_store; does NOT replace it.
    """

    def __init__(self):
        self._instances: List[ProviderInstance] = []
        self._active_id: Optional[str] = None
        self._loaded = False

    # ── Persistence ──────────────────────────────────────────────────────────

    async def load(self) -> List["ProviderInstance"]:
        """Load all instances from SQLite; seed default if empty."""
        raw = await memory_store.get_setting("provider_instances")
        if raw:
            self._instances = [ProviderInstance.from_dict(d) for d in raw]
            logger.info(f"[InstanceConfig] Loaded {len(self._instances)} instances from DB")
        else:
            self._instances = self._seed_default()
            await self.save(self._instances)
            logger.info("[InstanceConfig] Seeded default instances")

        active_raw = await memory_store.get_setting("active_provider_id")
        self._active_id = active_raw if isinstance(active_raw, str) else None

        # Ensure active_id points to a valid instance
        if self._active_id and not self.get_by_id(self._active_id):
            self._active_id = self._instances[0].id if self._instances else None

        self._loaded = True
        return self._instances

    async def save(self, instances: List["ProviderInstance"]) -> bool:
        """Persist instances list to SQLite."""
        data = [
            {
                "id": i.id, "type": i.type, "display_name": i.display_name,
                "base_url": i.base_url, "api_key": i.api_key,
                "default_model": i.default_model, "enabled": i.enabled, "timeout": i.timeout,
            }
            for i in instances
        ]
        ok = await memory_store.save_setting("provider_instances", data)
        if ok:
            self._instances = instances
        return ok

    async def get_active_id(self) -> Optional[str]:
        return self._active_id

    async def set_active_id(self, instance_id: str) -> bool:
        inst = self.get_by_id(instance_id)
        if not inst:
            logger.warning(f"[InstanceConfig] Cannot set active to unknown id: {instance_id}")
            return False
        ok = await memory_store.save_setting("active_provider_id", instance_id)
        if ok:
            self._active_id = instance_id
            logger.info(f"[InstanceConfig] Active instance set to: {instance_id}")
        return ok

    # ── In-memory lookups ───────────────────────────────────────────────────

    def get_all(self) -> List["ProviderInstance"]:
        return list(self._instances)

    def get_by_id(self, instance_id: str) -> Optional["ProviderInstance"]:
        for inst in self._instances:
            if inst.id == instance_id:
                return inst
        return None

    def get_active_instance(self) -> Optional["ProviderInstance"]:
        if self._active_id:
            inst = self.get_by_id(self._active_id)
            if inst and inst.enabled:
                return inst
        # Fallback: first enabled instance
        for inst in self._instances:
            if inst.enabled:
                return inst
        return self._instances[0] if self._instances else None

    def list_by_type(self, provider_type: str) -> List["ProviderInstance"]:
        return [i for i in self._instances if i.type == provider_type and i.enabled]

    # ── CRUD helpers (in-memory only, caller must save) ─────────────────────

    def add_instance(self, inst: "ProviderInstance") -> bool:
        if self.get_by_id(inst.id):
            logger.warning(f"[InstanceConfig] Duplicate instance id: {inst.id}")
            return False
        self._instances.append(inst)
        return True

    def update_instance(self, instance_id: str, inst: "ProviderInstance") -> bool:
        for i, existing in enumerate(self._instances):
            if existing.id == instance_id:
                self._instances[i] = inst
                return True
        return False

    def remove_instance(self, instance_id: str) -> bool:
        idx = None
        for i, existing in enumerate(self._instances):
            if existing.id == instance_id:
                idx = i
                break
        if idx is None:
            return False
        removed = self._instances.pop(idx)
        # If removed was active, switch to first enabled
        if self._active_id == instance_id:
            next_active = next((i for i in self._instances if i.enabled), None)
            self._active_id = next_active.id if next_active else None
        logger.info(f"[InstanceConfig] Removed instance: {removed.id}, new active: {self._active_id}")
        return True

    # ── Seed ────────────────────────────────────────────────────────────────

    def _seed_default(self) -> List["ProviderInstance"]:
        """Create a default ollama-default instance from env config."""
        defaults = []
        # Ollama — always seed
        defaults.append(ProviderInstance(
            id="ollama-default",
            type="ollama",
            display_name="Ollama (本地)",
            base_url=settings.ai.ollama.base_url,
            default_model=settings.ai.ollama.model,
            enabled=True,
            timeout=settings.ai.ollama.timeout,
        ))
        # OpenAI — only if API key is set in env
        if settings.ai.openai.api_key:
            defaults.append(ProviderInstance(
                id="openai-default",
                type="openai",
                display_name="OpenAI (云端)",
                api_key=settings.ai.openai.api_key,
                base_url=settings.ai.openai.base_url,
                default_model=settings.ai.openai.model,
                enabled=True,
                timeout=settings.ai.openai.timeout,
            ))
        # Anthropic — only if API key is set in env
        if settings.ai.anthropic.api_key:
            defaults.append(ProviderInstance(
                id="anthropic-default",
                type="anthropic",
                display_name="Anthropic (云端)",
                api_key=settings.ai.anthropic.api_key,
                base_url=settings.ai.anthropic.base_url,
                default_model=settings.ai.anthropic.model,
                enabled=True,
                timeout=settings.ai.anthropic.timeout,
            ))
        return defaults


# Module-level singleton (lazily loaded on first access)
_instance_store: Optional[InstanceConfigStore] = None


def get_instance_store() -> InstanceConfigStore:
    global _instance_store
    if _instance_store is None:
        _instance_store = InstanceConfigStore()
    return _instance_store
