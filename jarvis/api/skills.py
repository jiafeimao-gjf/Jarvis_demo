# jarvis/api/skills.py
"""Skill 管理 API — CRUD + 启用/分组/标签 + 刷新磁盘"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request

from pydantic import BaseModel, Field

from jarvis.services.skill_store import (
    get_skill_store, Skill, SkillConfig,
    _validate_skill_id, DEFAULT_GROUP,
)
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/skills", tags=["skills"])


# ── Request/Response models ─────────────────────────────────────────────────

class SkillCreateRequest(BaseModel):
    """Create a new skill."""
    id: str
    name: str = ""
    description: str = ""
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=lambda: [DEFAULT_GROUP])
    enabled: bool = True


class SkillUpdateRequest(BaseModel):
    """Partial update — only supplied fields are changed."""
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    groups: Optional[list[str]] = None
    enabled: Optional[bool] = None
    order: Optional[int] = None


class ReorderRequest(BaseModel):
    ordered_ids: list[str]


class ActiveGroupsRequest(BaseModel):
    groups: list[str]


class TagsRequest(BaseModel):
    tags: list[str]


class GroupsRequest(BaseModel):
    groups: list[str]


class RenameTagRequest(BaseModel):
    old: str
    new: str


class RenameGroupRequest(BaseModel):
    old: str
    new: str


class DeleteRequest(BaseModel):
    name: str


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_skills(include_missing: bool = False):
    """List all skills with metadata. include_missing=true 包含磁盘已删除但 DB 仍存的记录."""
    store = get_skill_store()
    await store.load()
    return {
        "skills": [s.to_dict() for s in store.list_all(include_missing=include_missing)],
        "count": len(store.list_all(include_missing=include_missing)),
    }


@router.get("/groups", response_model=dict)
async def list_groups():
    """List all known groups with skill_count + is_active."""
    store = get_skill_store()
    await store.load()
    return {"groups": store.get_groups()}


@router.get("/tags", response_model=dict)
async def list_tags():
    """List all known tags with skill_count."""
    store = get_skill_store()
    await store.load()
    return {"tags": store.get_tags()}


@router.get("/config", response_model=dict)
async def get_config():
    """Get global skill config (active_groups, known_tags, known_groups)."""
    store = get_skill_store()
    await store.load()
    return {"config": store._config.to_dict()}


@router.put("/config/active_groups", response_model=dict)
async def set_active_groups(body: ActiveGroupsRequest):
    """Set which groups are currently active for system prompt injection."""
    store = get_skill_store()
    await store.load()
    ok = await store.set_active_groups(body.groups)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save active groups")
    return {"active_groups": store._config.active_groups}


@router.put("/config/tags", response_model=dict)
async def set_known_tags(body: TagsRequest):
    store = get_skill_store()
    await store.load()
    ok = await store.set_known_tags(body.tags)
    return {"tags": store._config.known_tags, "ok": ok}


@router.put("/config/groups", response_model=dict)
async def set_known_groups(body: GroupsRequest):
    store = get_skill_store()
    await store.load()
    ok = await store.set_known_groups(body.groups)
    return {"groups": store._config.known_groups, "ok": ok}


@router.post("/tags/rename", response_model=dict)
async def rename_tag(body: RenameTagRequest):
    store = get_skill_store()
    await store.load()
    ok = await store.rename_tag(body.old, body.new)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid rename (empty or same name)")
    return {"ok": ok}


@router.post("/groups/rename", response_model=dict)
async def rename_group(body: RenameGroupRequest):
    store = get_skill_store()
    await store.load()
    ok = await store.rename_group(body.old, body.new)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid rename or default group cannot be renamed")
    return {"ok": ok}


@router.delete("/tags/{tag}", response_model=dict)
async def delete_tag(tag: str):
    store = get_skill_store()
    await store.load()
    ok = await store.delete_tag(tag)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete tag")
    return {"ok": ok}


@router.delete("/groups/{group}", response_model=dict)
async def delete_group(group: str):
    store = get_skill_store()
    await store.load()
    if group == DEFAULT_GROUP:
        raise HTTPException(status_code=400, detail="Cannot delete default group")
    ok = await store.delete_group(group)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete group")
    return {"ok": ok}


@router.post("/refresh", response_model=dict)
async def refresh_from_disk():
    """Re-scan workspace/skills/ for new files; mark missing files."""
    store = get_skill_store()
    await store.load()
    await store.refresh_from_disk()
    return {
        "ok": True,
        "skills": [s.to_dict() for s in store.list_all(include_missing=True)],
        "count": len(store.list_all(include_missing=True)),
    }


@router.get("/{skill_id}", response_model=dict)
async def get_skill(skill_id: str):
    """Get full skill (with content)."""
    store = get_skill_store()
    await store.load()
    skill = store.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return {"skill": skill.to_dict()}


@router.post("", response_model=dict)
async def create_skill(body: SkillCreateRequest):
    """Create a new skill (write markdown file + DB row)."""
    store = get_skill_store()
    await store.load()

    if not _validate_skill_id(body.id):
        raise HTTPException(status_code=400, detail="Invalid skill id (must be kebab-case, 3-64 chars)")
    if store.get(body.id):
        raise HTTPException(status_code=409, detail=f"Skill '{body.id}' already exists")

    skill = Skill(
        id=body.id,
        name=body.name or body.id,
        description=body.description or "(无描述)",
        content=body.content,
        tags=body.tags,
        groups=body.groups or [DEFAULT_GROUP],
        enabled=body.enabled,
    )
    try:
        created = await store.create(skill)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Skills] Create failed for {body.id}: {e}")
        raise HTTPException(status_code=500, detail=f"Create failed: {e}")

    logger.info(f"[Skills] Created: {created.id}")
    return {"skill": created.to_dict()}


@router.put("/{skill_id}", response_model=dict)
async def update_skill(skill_id: str, body: SkillUpdateRequest):
    """Partial update of an existing skill."""
    store = get_skill_store()
    await store.load()
    if not store.get(skill_id):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    partial = body.model_dump(exclude_unset=True)
    try:
        updated = await store.update(skill_id, partial)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"[Skills] Update failed for {skill_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Update failed: {e}")

    logger.info(f"[Skills] Updated: {skill_id}")
    return {"skill": updated.to_dict()}


@router.delete("/{skill_id}", response_model=dict)
async def delete_skill(skill_id: str):
    """Delete a skill (remove file + DB row)."""
    store = get_skill_store()
    await store.load()
    if not store.get(skill_id):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    ok = await store.delete(skill_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Delete failed")
    logger.info(f"[Skills] Deleted: {skill_id}")
    return {"ok": True}


@router.patch("/{skill_id}/toggle", response_model=dict)
async def toggle_skill(skill_id: str):
    """Toggle enabled flag."""
    store = get_skill_store()
    await store.load()
    ok = await store.toggle(skill_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    skill = store.get(skill_id)
    return {"skill": skill.to_dict() if skill else None}


@router.patch("/reorder", response_model=dict)
async def reorder_skills(body: ReorderRequest):
    """Bulk reorder by ID list."""
    store = get_skill_store()
    await store.load()
    ok = await store.reorder(body.ordered_ids)
    if not ok:
        raise HTTPException(status_code=500, detail="Reorder failed")
    return {"ok": True, "skills": [s.to_dict() for s in store.list_all()]}
