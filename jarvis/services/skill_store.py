# jarvis/services/skill_store.py
"""Skill 数据存储 — 文件系统 (markdown) + SQLite 元数据 混合存储

设计要点:
- markdown 文件 (workspace/skills/<id>/skill.md) 是 git-tracked 内容来源, 人工可编辑
- SQLite (via memory_store.save_setting) 存 enabled/tags/groups/order/timestamps 元数据
- chat_engine._build_system_prompt() 是 sync, 所以 get_enabled_for_active_groups() 走内存缓存
- skill_store 在应用启动时 (main.startup_event) eager load, 之后所有读都是同步
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jarvis.config import settings
from jarvis.core.memory_store import memory_store
from jarvis.services.skill_loader import load_skills, SkillInfo
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


# ── Constants ───────────────────────────────────────────────────────────────

# workspace/skills/<id>/skill.md lives under the workspace/ subdirectory
WORKSPACE_ROOT = Path(__file__).parent.parent.parent / "workspace"  # jarvis/../workspace
SKILLS_DIR_NAME = "skills"  # workspace/skills/

SETTING_KEY_SKILLS = "skills_v1"
SETTING_KEY_CONFIG = "skill_config_v1"

YAML_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)
DEFAULT_GROUP = "default"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_skill_id(skill_id: str) -> bool:
    """kebab-case, 3-64 chars, lowercase alphanumeric + dash + underscore (no leading/trailing - or _)"""
    if not skill_id:
        return False
    if not (3 <= len(skill_id) <= 64):
        return False
    return bool(re.match(r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$", skill_id))


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse simple YAML frontmatter. Returns ({key: val}, body)."""
    m = YAML_FRONT_RE.match(text)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, m.group(2)


def _find_skill_md(skill_dir: Path) -> Optional[Path]:
    """Find the markdown file for a skill (case-insensitive: skill.md or SKILL.md)."""
    for name in ("skill.md", "SKILL.md"):
        p = skill_dir / name
        if p.exists():
            return p
    return None


def _build_frontmatter(name: str, description: str, tags: list[str]) -> str:
    """Build a YAML frontmatter block."""
    lines = ["---", f"name: {name}", f"description: {description}"]
    if tags:
        lines.append(f"tags: {','.join(tags)}")
    lines.append("---")
    return "\n".join(lines)


# ── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class Skill:
    """A managed skill — content on disk + metadata in DB."""
    id: str
    name: str = ""
    description: str = ""
    content: str = ""                 # markdown body (without frontmatter)
    tags: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=lambda: [DEFAULT_GROUP])
    enabled: bool = True
    order: int = 0
    file_path: str = ""               # workspace/skills/<id>/skill.md
    created_at: str = ""
    updated_at: str = ""
    missing: bool = False             # DB row exists but file was deleted externally

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "tags": list(self.tags),
            "groups": list(self.groups),
            "enabled": self.enabled,
            "order": self.order,
            "file_path": self.file_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "missing": self.missing,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Skill":
        # Drop unknown keys for forward-compat
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class SkillConfig:
    """Global skill configuration."""
    active_groups: list[str] = field(default_factory=lambda: [DEFAULT_GROUP])
    known_tags: list[str] = field(default_factory=list)
    known_groups: list[str] = field(default_factory=lambda: [DEFAULT_GROUP])

    def to_dict(self) -> dict:
        return {
            "active_groups": list(self.active_groups),
            "known_tags": list(self.known_tags),
            "known_groups": list(self.known_groups),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SkillConfig":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})


# ── Store ───────────────────────────────────────────────────────────────────

class SkillStore:
    """In-memory cache + SQLite persistence for skill metadata.
    Files are managed on disk alongside.

    Public API:
        await load()                              — load from DB, seed from disk if first run
        list_all(include_missing=False) -> list   — all skills
        get(id) -> Skill | None                   — single skill
        get_enabled_for_active_groups() -> list   — sync, filtered for system prompt
        async create(skill)                       — write file + DB
        async update(id, skill)                   — write file + DB
        async delete(id)                          — delete file + DB
        async toggle(id)                          — flip enabled
        async reorder(ordered_ids)                — bulk reorder
        async refresh_from_disk()                 — rescan disk, mark missing/add new
        get_groups() / get_tags()                 — known groups/tags with counts
        async set_active_groups(groups)
        async set_known_tags(tags) / async set_known_groups(groups)
    """

    def __init__(self, workspace_root: Optional[Path] = None):
        self._workspace_root = workspace_root or WORKSPACE_ROOT
        self._skills_dir = self._workspace_root / SKILLS_DIR_NAME
        self._skills: dict[str, Skill] = {}
        self._config: SkillConfig = SkillConfig()
        self._loaded = False
        self._cached_enabled_skills: Optional[list[Skill]] = None

    # ── Persistence ──────────────────────────────────────────────────────────

    async def load(self) -> list[Skill]:
        """Load from DB; if first run, seed from existing markdown files on disk."""
        # Load skills list
        raw = await memory_store.get_setting(SETTING_KEY_SKILLS)
        if raw:
            self._skills = {s["id"]: Skill.from_dict(s) for s in raw}
            logger.info(f"[SkillStore] Loaded {len(self._skills)} skills from DB")
        else:
            await self._seed_from_disk()
            logger.info(f"[SkillStore] Seeded {len(self._skills)} skills from disk")

        # Load config
        cfg_raw = await memory_store.get_setting(SETTING_KEY_CONFIG)
        if cfg_raw:
            self._config = SkillConfig.from_dict(cfg_raw)
        else:
            await self._save_config()

        # Always reconcile disk state (fast path: no changes if nothing moved)
        await self.refresh_from_disk()

        self._loaded = True
        self._invalidate_cache()
        return list(self._skills.values())

    async def save(self) -> bool:
        """Persist skills list to DB."""
        data = [s.to_dict() for s in self._skills.values()]
        ok = await memory_store.save_setting(SETTING_KEY_SKILLS, data)
        if ok:
            self._invalidate_cache()
        return ok

    async def _save_config(self) -> bool:
        return await memory_store.save_setting(SETTING_KEY_CONFIG, self._config.to_dict())

    # ── Seed & refresh ──────────────────────────────────────────────────────

    async def _seed_from_disk(self) -> None:
        """First-run: import all existing workspace/skills/*.md into DB."""
        infos: list[SkillInfo] = load_skills(self._skills_dir)
        for idx, info in enumerate(infos):
            md_path = _find_skill_md(self._skills_dir / info.path)
            content = ""
            if md_path and md_path.exists():
                try:
                    content = md_path.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning(f"[SkillStore] Failed to read {md_path}: {e}")
            # Strip frontmatter from content
            fm, body = _parse_frontmatter(content)
            raw_tags = fm.get("tags", "")
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()] if raw_tags else []

            # ID = directory name (always kebab-case), YAML name → display name
            skill_id = Path(info.path).name
            skill = Skill(
                id=skill_id,
                name=fm.get("name", skill_id),
                description=info.description or fm.get("description", "(无描述)"),
                content=body,
                tags=tags,
                groups=[DEFAULT_GROUP],
                enabled=True,
                order=idx,
                file_path=f"workspace/skills/{info.path}/skill.md",
                created_at=_now_iso(),
                updated_at=_now_iso(),
            )
            self._skills[skill.id] = skill

            for t in tags:
                if t not in self._config.known_tags:
                    self._config.known_tags.append(t)

        await self.save()
        await self._save_config()

    async def refresh_from_disk(self) -> None:
        """Rescan disk; add new files as DB rows, mark missing files.

        - Newly discovered files: append to DB (default enabled=True, groups=[default], tags=[])
        - Files deleted from disk (DB row exists): mark missing=True (don't delete, preserve user edits)
        - Files modified on disk: re-read content/name/description/tags (but preserve enabled/groups/order)
        """
        infos: list[SkillInfo] = load_skills(self._skills_dir)
        on_disk: set[str] = set()

        for idx, info in enumerate(infos):
            skill_id = Path(info.path).name
            on_disk.add(skill_id)
            md_path = _find_skill_md(self._skills_dir / info.path)
            if not md_path:
                continue
            try:
                content = md_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"[SkillStore] Failed to read {md_path}: {e}")
                continue

            fm, body = _parse_frontmatter(content)
            raw_tags = fm.get("tags", "")
            new_tags = [t.strip() for t in raw_tags.split(",") if t.strip()] if raw_tags else []

            existing = self._skills.get(skill_id)
            if existing:
                # Update content from disk but preserve user metadata
                existing.missing = False
                existing.name = fm.get("name", existing.name or skill_id)
                existing.description = fm.get("description", existing.description)
                existing.content = body
                existing.file_path = f"workspace/skills/{info.path}/skill.md"
                existing.tags = new_tags if new_tags else existing.tags
                for t in new_tags:
                    if t not in self._config.known_tags:
                        self._config.known_tags.append(t)
            else:
                skill = Skill(
                    id=skill_id,
                    name=fm.get("name", skill_id),
                    description=fm.get("description", info.description or "(无描述)"),
                    content=body,
                    tags=new_tags,
                    groups=[DEFAULT_GROUP],
                    enabled=True,
                    order=len(self._skills) + idx,
                    file_path=f"workspace/skills/{info.path}/skill.md",
                    created_at=_now_iso(),
                    updated_at=_now_iso(),
                )
                self._skills[skill.id] = skill
                for t in new_tags:
                    if t not in self._config.known_tags:
                        self._config.known_tags.append(t)

        # Mark missing
        any_missing = False
        for sid, skill in self._skills.items():
            if sid not in on_disk and not skill.missing:
                skill.missing = True
                any_missing = True
                logger.warning(f"[SkillStore] Marking missing: {sid}")
            elif sid in on_disk and skill.missing:
                skill.missing = False

        if any_missing:
            await self.save()
            await self._save_config()

    # ── In-memory lookups ───────────────────────────────────────────────────

    def list_all(self, include_missing: bool = False) -> list[Skill]:
        skills = list(self._skills.values())
        if not include_missing:
            skills = [s for s in skills if not s.missing]
        skills.sort(key=lambda s: (s.order, s.id))
        return skills

    def get(self, skill_id: str) -> Optional[Skill]:
        return self._skills.get(skill_id)

    def get_enabled_for_active_groups(self) -> list[Skill]:
        """Sync read — used by chat_engine._build_system_prompt.

        Filter: enabled=True AND not missing AND (no groups OR groups ∩ active_groups ≠ ∅)
        Cached until next mutation (create/update/delete/toggle/reorder/refresh).
        """
        if not self._loaded:
            return []
        if self._cached_enabled_skills is not None:
            return self._cached_enabled_skills

        active = set(self._config.active_groups)
        out = []
        for s in self._skills.values():
            if not s.enabled or s.missing:
                continue
            if not s.groups or (set(s.groups) & active):
                out.append(s)
        out.sort(key=lambda s: (s.order, s.id))
        self._cached_enabled_skills = out
        return out

    def get_groups(self) -> list[dict]:
        """Return [{name, skill_count, is_active}]."""
        active = set(self._config.active_groups)
        all_names = set(self._config.known_groups) or {DEFAULT_GROUP}
        for s in self._skills.values():
            for g in s.groups:
                all_names.add(g)
        out = []
        for g in sorted(all_names):
            count = sum(1 for s in self._skills.values() if g in s.groups)
            out.append({"name": g, "skill_count": count, "is_active": g in active})
        return out

    def get_tags(self) -> list[dict]:
        """Return [{name, skill_count}]."""
        all_names = set(self._config.known_tags)
        for s in self._skills.values():
            for t in s.tags:
                all_names.add(t)
        out = []
        for t in sorted(all_names):
            count = sum(1 for s in self._skills.values() if t in s.tags)
            out.append({"name": t, "skill_count": count})
        return out

    def _invalidate_cache(self) -> None:
        self._cached_enabled_skills = None

    # ── File I/O ────────────────────────────────────────────────────────────

    def _write_file(self, skill: Skill) -> None:
        """Write markdown file to disk with YAML frontmatter."""
        skill_dir = self._skills_dir / skill.id
        full = skill_dir / "skill.md"
        skill_dir.mkdir(parents=True, exist_ok=True)
        fm = _build_frontmatter(skill.name, skill.description, skill.tags)
        body = skill.content.strip() if skill.content else ""
        text = f"{fm}\n\n{body}\n" if body else f"{fm}\n"
        full.write_text(text, encoding="utf-8")
        # Store path relative to project root for git-trackability
        try:
            rel = full.relative_to(WORKSPACE_ROOT.parent)
            skill.file_path = str(rel)
        except ValueError:
            skill.file_path = str(full)

    def _delete_file(self, skill: Skill) -> None:
        skill_dir = self._skills_dir / skill.id
        full = skill_dir / "skill.md"
        try:
            if full.exists():
                full.unlink()
            if skill_dir.exists() and not any(skill_dir.iterdir()):
                skill_dir.rmdir()
        except Exception as e:
            logger.warning(f"[SkillStore] Failed to remove {full}: {e}")

    # ── CRUD ───────────────────────────────────────────────────────────────

    async def create(self, skill: Skill) -> Skill:
        if not _validate_skill_id(skill.id):
            raise ValueError(f"Invalid skill id: {skill.id!r} (must be kebab-case, 3-64 chars)")
        if skill.id in self._skills:
            raise ValueError(f"Skill '{skill.id}' already exists")

        # Defaults
        if not skill.name:
            skill.name = skill.id
        if not skill.description:
            skill.description = "(无描述)"
        # Empty groups [] means "always available across all scenes"; only normalize if explicit None
        if skill.groups is None:
            skill.groups = [DEFAULT_GROUP]
        if not skill.order:  # 0 or None → auto-assign
            skill.order = max((s.order for s in self._skills.values()), default=-1) + 1
        skill.created_at = skill.updated_at = _now_iso()
        skill.missing = False

        # Track tags
        for t in skill.tags:
            if t not in self._config.known_tags:
                self._config.known_tags.append(t)
        # Track groups
        for g in skill.groups:
            if g not in self._config.known_groups:
                self._config.known_groups.append(g)

        self._write_file(skill)
        self._skills[skill.id] = skill
        await self.save()
        await self._save_config()
        return skill

    async def update(self, skill_id: str, partial: dict) -> Skill:
        existing = self._skills.get(skill_id)
        if not existing:
            raise KeyError(f"Skill '{skill_id}' not found")

        # Apply partial fields (excluding id, file_path, created_at)
        mutable = {"name", "description", "content", "tags", "groups", "enabled", "order"}
        for k, v in partial.items():
            if k in mutable:
                setattr(existing, k, v)
        existing.updated_at = _now_iso()
        existing.missing = False

        # Track new tags/groups
        for t in existing.tags:
            if t not in self._config.known_tags:
                self._config.known_tags.append(t)
        for g in existing.groups:
            if g not in self._config.known_groups:
                self._config.known_groups.append(g)

        self._write_file(existing)
        await self.save()
        await self._save_config()
        return existing

    async def delete(self, skill_id: str) -> bool:
        skill = self._skills.get(skill_id)
        if not skill:
            return False
        self._delete_file(skill)
        del self._skills[skill_id]
        await self.save()
        self._invalidate_cache()
        return True

    async def toggle(self, skill_id: str) -> bool:
        skill = self._skills.get(skill_id)
        if not skill:
            return False
        skill.enabled = not skill.enabled
        skill.updated_at = _now_iso()
        ok = await self.save()
        return ok

    async def reorder(self, ordered_ids: list[str]) -> bool:
        """Set order_index based on input order."""
        for idx, sid in enumerate(ordered_ids):
            if sid in self._skills:
                self._skills[sid].order = idx
        return await self.save()

    # ── Config ─────────────────────────────────────────────────────────────

    async def set_active_groups(self, groups: list[str]) -> bool:
        if not groups:
            groups = [DEFAULT_GROUP]
        # Filter to known
        known = set(self._config.known_groups) | {DEFAULT_GROUP}
        self._config.active_groups = [g for g in groups if g in known] or [DEFAULT_GROUP]
        self._invalidate_cache()
        return await self._save_config()

    async def set_known_tags(self, tags: list[str]) -> bool:
        self._config.known_tags = list(dict.fromkeys(tags))  # dedupe, preserve order
        return await self._save_config()

    async def set_known_groups(self, groups: list[str]) -> bool:
        if not groups:
            groups = [DEFAULT_GROUP]
        self._config.known_groups = list(dict.fromkeys(groups))
        # Ensure DEFAULT is present
        if DEFAULT_GROUP not in self._config.known_groups:
            self._config.known_groups.insert(0, DEFAULT_GROUP)
        # Filter active_groups to known
        self._config.active_groups = [g for g in self._config.active_groups
                                       if g in self._config.known_groups] or [DEFAULT_GROUP]
        return await self._save_config()

    async def rename_tag(self, old: str, new: str) -> bool:
        new = new.strip()
        if not new or old == new:
            return False
        for s in self._skills.values():
            if old in s.tags:
                s.tags = [new if t == old else t for t in s.tags]
                s.updated_at = _now_iso()
                self._write_file(s)
        if old in self._config.known_tags:
            self._config.known_tags = [new if t == old else t for t in self._config.known_tags]
        return await self.save() and await self._save_config()

    async def rename_group(self, old: str, new: str) -> bool:
        new = new.strip()
        if not new or old == new:
            return False
        for s in self._skills.values():
            if old in s.groups:
                s.groups = [new if g == old else g for g in s.groups]
                s.updated_at = _now_iso()
                self._write_file(s)
        if old in self._config.known_groups:
            self._config.known_groups = [new if g == old else g for g in self._config.known_groups]
        if old in self._config.active_groups:
            self._config.active_groups = [new if g == old else g for g in self._config.active_groups]
        return await self.save() and await self._save_config()

    async def delete_tag(self, tag: str) -> bool:
        for s in self._skills.values():
            if tag in s.tags:
                s.tags = [t for t in s.tags if t != tag]
                s.updated_at = _now_iso()
                self._write_file(s)
        self._config.known_tags = [t for t in self._config.known_tags if t != tag]
        return await self.save() and await self._save_config()

    async def delete_group(self, group: str) -> bool:
        if group == DEFAULT_GROUP:
            return False  # can't delete default
        for s in self._skills.values():
            if group in s.groups:
                s.groups = [g for g in s.groups if g != group]
                if not s.groups:
                    s.groups = [DEFAULT_GROUP]
                s.updated_at = _now_iso()
                self._write_file(s)
        self._config.known_groups = [g for g in self._config.known_groups if g != group]
        self._config.active_groups = [g for g in self._config.active_groups if g != group]
        return await self.save() and await self._save_config()


# Module-level singleton
_skill_store: Optional[SkillStore] = None


def get_skill_store() -> SkillStore:
    global _skill_store
    if _skill_store is None:
        _skill_store = SkillStore()
    return _skill_store


# Convenience alias used in chat_engine (sync read path)
def skill_store() -> SkillStore:
    """Backwards-compatible alias — same as get_skill_store() but callable."""
    return get_skill_store()
