# jarvis/api/providers.py
"""Provider Instance API — CRUD + active selection"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request

from jarvis.services.ai.instance_config import get_instance_store, ProviderInstance
from jarvis.services.ai.registry import ProviderRegistry
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/providers", tags=["providers"])


# ── Request/Response models ─────────────────────────────────────────────────

from pydantic import BaseModel


class SetActiveRequest(BaseModel):
    instance_id: str


class InstanceUpdateRequest(BaseModel):
    type: str
    display_name: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: str = ""
    enabled: bool = True
    timeout: float = 60.0


class TestResult(BaseModel):
    ok: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_instances():
    """List all provider instances (api_key redacted)."""
    store = get_instance_store()
    await store.load()
    return {
        "instances": [i.to_dict(redact_secrets=True) for i in store.get_all()],
        "active_id": store._active_id,
    }


@router.post("", response_model=dict)
async def create_instance(inst: ProviderInstance):
    """Add a new provider instance."""
    store = get_instance_store()
    await store.load()
    if not inst.id or not inst.type:
        raise HTTPException(status_code=400, detail="id and type are required")
    if store.get_by_id(inst.id):
        raise HTTPException(status_code=409, detail=f"Instance '{inst.id}' already exists")
    store.add_instance(inst)
    await store.save(store.get_all())
    logger.info(f"[Providers] Created instance: {inst.id}")
    return {"instance": inst.to_dict(redact_secrets=True)}


@router.put("/{instance_id}", response_model=dict)
async def update_instance(instance_id: str, body: InstanceUpdateRequest):
    """Update an existing provider instance."""
    store = get_instance_store()
    await store.load()
    existing = store.get_by_id(instance_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")
    updated = ProviderInstance(
        id=instance_id,
        type=body.type,
        display_name=body.display_name,
        base_url=body.base_url,
        api_key=body.api_key or existing.api_key,  # keep existing if not provided
        default_model=body.default_model,
        enabled=body.enabled,
        timeout=body.timeout,
    )
    store.update_instance(instance_id, updated)
    await store.save(store.get_all())
    logger.info(f"[Providers] Updated instance: {instance_id}")
    return {"instance": updated.to_dict(redact_secrets=True)}


@router.delete("/{instance_id}")
async def delete_instance(instance_id: str):
    """Delete a provider instance."""
    store = get_instance_store()
    await store.load()
    if not store.get_by_id(instance_id):
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")
    store.remove_instance(instance_id)
    await store.save(store.get_all())
    logger.info(f"[Providers] Deleted instance: {instance_id}")
    return {"success": True, "active_id": store._active_id}


@router.post("/active", response_model=dict)
async def set_active(body: SetActiveRequest):
    """Set the active provider instance (POST, not PUT, to avoid route conflict with /{instance_id})."""
    store = get_instance_store()
    await store.load()
    inst = store.get_by_id(body.instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance '{body.instance_id}' not found")
    if not inst.enabled:
        raise HTTPException(status_code=400, detail="Cannot activate a disabled instance")
    await store.set_active_id(body.instance_id)
    # Import here to avoid circular dependency
    from jarvis.core.mediator import mediator
    await mediator.reload_ai_router()
    logger.info(f"[Providers] Active instance set to: {body.instance_id}")
    return {"success": True, "active_id": body.instance_id}


@router.get("/active", response_model=dict)
async def get_active():
    """Get the currently active provider instance."""
    store = get_instance_store()
    await store.load()
    active = store.get_active_instance()
    if not active:
        raise HTTPException(status_code=404, detail="No active provider instance")
    return {"instance": active.to_dict(redact_secrets=True)}


@router.post("/{instance_id}/test", response_model=TestResult)
async def test_instance(instance_id: str):
    """Test connectivity to a provider instance."""
    store = get_instance_store()
    await store.load()
    inst = store.get_by_id(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

    import time
    from jarvis.services.ai.registry import ProviderRegistry

    t0 = time.monotonic()
    try:
        config = {}
        if inst.base_url:
            config["base_url"] = inst.base_url
        if inst.api_key:
            config["api_key"] = inst.api_key
        config["timeout"] = inst.timeout
        config = {k: v for k, v in config.items() if v is not None}

        client = ProviderRegistry.create_client(inst.default_model, **config)
        ok = await client.health_check()
        latency = (time.monotonic() - t0) * 1000
        if not ok:
            return TestResult(ok=False, error="health_check returned False")
        return TestResult(ok=True, latency_ms=round(latency, 1))
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        logger.warning(f"[Providers] Test failed for {instance_id}: {e}")
        return TestResult(ok=False, latency_ms=round(latency, 1), error=str(e))


@router.get("/{instance_id}/models")
async def list_instance_models(instance_id: str, force_refresh: bool = False):
    """List available models for an instance (via the instance's base_url)."""
    store = get_instance_store()
    await store.load()
    inst = store.get_by_id(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

    try:
        config = {}
        if inst.base_url:
            config["base_url"] = inst.base_url
        if inst.api_key:
            config["api_key"] = inst.api_key
        config["timeout"] = inst.timeout
        config = {k: v for k, v in config.items() if v is not None}

        client = ProviderRegistry.create_client(inst.default_model, **config)
        models = await client.list_models(force_refresh=force_refresh)
        return {"models": models}
    except Exception as e:
        logger.warning(f"[Providers] list_models failed for {instance_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to list models: {e}")
