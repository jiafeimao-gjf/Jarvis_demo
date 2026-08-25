# tests/test_skill_store.py
"""Tests for Skill Management Module — skill_store.py + skill_loader integration"""
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarvis.services.skill_store import (
    Skill, SkillConfig, SkillStore,
    _validate_skill_id, _parse_frontmatter, _build_frontmatter,
    get_skill_store, DEFAULT_GROUP,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def workspace_dir():
    """Create a temp workspace with skills/ subdirectory + sample skills."""
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_skills_test_"))
    skills_dir = tmp / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # Skill A — full frontmatter
    (skills_dir / "skill-a").mkdir()
    (skills_dir / "skill-a" / "skill.md").write_text(
        "---\nname: Skill A\ndescription: First test skill\ntags: demo,alpha\n---\n\n# Body A\n",
        encoding="utf-8",
    )

    # Skill B — uppercase file name
    (skills_dir / "skill-b").mkdir()
    (skills_dir / "skill-b" / "SKILL.md").write_text(
        "---\nname: Skill B\ndescription: Second test skill\n---\n\nBody B content\n",
        encoding="utf-8",
    )

    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def store(workspace_dir):
    """Create a SkillStore bound to the temp workspace, with mocked memory_store."""
    s = SkillStore(workspace_root=workspace_dir)
    return s


@pytest.fixture
def mock_memory_store():
    """Mock memory_store so tests don't touch the real SQLite DB."""
    fake_data = {}
    async def get_setting(key):
        return fake_data.get(key)
    async def save_setting(key, value):
        fake_data[key] = value
        return True
    async def get_all_settings():
        return dict(fake_data)

    mem = AsyncMock()
    mem.get_setting = AsyncMock(side_effect=get_setting)
    mem.save_setting = AsyncMock(side_effect=save_setting)
    mem.get_all_settings = AsyncMock(side_effect=get_all_settings)
    return mem


# ── Helper / unit tests ─────────────────────────────────────────────────────

class TestHelpers:
    def test_validate_skill_id_accepts_kebab(self):
        assert _validate_skill_id("hello-world") is True
        assert _validate_skill_id("abc") is True
        assert _validate_skill_id("skill_coder-2") is True
        assert _validate_skill_id("a" * 64) is True

    def test_validate_skill_id_rejects_bad(self):
        assert _validate_skill_id("") is False
        assert _validate_skill_id("ab") is False  # too short
        assert _validate_skill_id("a" * 65) is False  # too long
        assert _validate_skill_id("Hello-World") is False  # uppercase
        assert _validate_skill_id("hello world") is False  # space
        assert _validate_skill_id("-leading-dash") is False  # bad start
        assert _validate_skill_id("trailing-") is False  # bad end

    def test_parse_frontmatter_with_yaml(self):
        text = "---\nname: X\ndescription: Y\n---\n\nbody here"
        fm, body = _parse_frontmatter(text)
        assert fm == {"name": "X", "description": "Y"}
        assert "body here" in body

    def test_parse_frontmatter_without_yaml(self):
        text = "no frontmatter here"
        fm, body = _parse_frontmatter(text)
        assert fm == {}
        assert body == "no frontmatter here"

    def test_build_frontmatter_roundtrip(self):
        fm = _build_frontmatter("My Skill", "desc", ["a", "b"])
        assert "name: My Skill" in fm
        assert "description: desc" in fm
        assert "tags: a,b" in fm


# ── Skill dataclass ─────────────────────────────────────────────────────────

class TestSkillDataclass:
    def test_to_from_dict_roundtrip(self):
        s = Skill(
            id="x", name="X", description="d", content="body",
            tags=["t1", "t2"], groups=["g1"], enabled=False, order=5,
            file_path="workspace/skills/x/skill.md",
        )
        d = s.to_dict()
        assert d["id"] == "x"
        assert d["tags"] == ["t1", "t2"]
        assert d["enabled"] is False

        s2 = Skill.from_dict(d)
        assert s2.id == s.id
        assert s2.tags == s.tags
        assert s2.enabled == s.enabled

    def test_from_dict_drops_unknown_keys(self):
        s = Skill.from_dict({"id": "x", "future_field": "ignored"})
        assert s.id == "x"


class TestSkillConfigDataclass:
    def test_default_config(self):
        c = SkillConfig()
        assert c.active_groups == [DEFAULT_GROUP]
        assert c.known_tags == []
        assert c.known_groups == [DEFAULT_GROUP]

    def test_roundtrip(self):
        c = SkillConfig(active_groups=["dev", "creative"], known_tags=["x", "y"], known_groups=["dev", "creative"])
        d = c.to_dict()
        c2 = SkillConfig.from_dict(d)
        assert c2.active_groups == ["dev", "creative"]
        assert c2.known_tags == ["x", "y"]


# ── SkillStore — seed ───────────────────────────────────────────────────────

class TestSkillStoreSeed:
    @pytest.mark.asyncio
    async def test_seed_imports_existing_files(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
        skills = store.list_all()
        ids = {s.id for s in skills}
        assert ids == {"skill-a", "skill-b"}

    @pytest.mark.asyncio
    async def test_seed_preserves_tags_from_frontmatter(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
        skill_a = store.get("skill-a")
        assert skill_a is not None
        assert skill_a.tags == ["demo", "alpha"]
        assert skill_a.name == "Skill A"
        assert skill_a.description == "First test skill"

    @pytest.mark.asyncio
    async def test_seed_default_group_assigned(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
        for s in store.list_all():
            assert DEFAULT_GROUP in s.groups

    @pytest.mark.asyncio
    async def test_seed_uppercase_md_file_is_found(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
        assert store.get("skill-b") is not None


# ── SkillStore — CRUD ───────────────────────────────────────────────────────

class TestSkillStoreCRUD:
    @pytest.mark.asyncio
    async def test_create_writes_file_and_db(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            skill = Skill(id="new-skill", name="New", description="D", content="body text", tags=["t1"])
            created = await store.create(skill)

        assert created.id == "new-skill"
        assert created.name == "New"
        full = store._skills_dir / "new-skill" / "skill.md"
        assert full.exists()
        content = full.read_text(encoding="utf-8")
        assert "name: New" in content
        assert "body text" in content
        # Verify tracked in known_tags
        assert "t1" in store._config.known_tags

    @pytest.mark.asyncio
    async def test_create_rejects_duplicate_id(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="dup", name="X"))
            with pytest.raises(ValueError, match="already exists"):
                await store.create(Skill(id="dup", name="Y"))

    @pytest.mark.asyncio
    async def test_create_rejects_invalid_id(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            with pytest.raises(ValueError, match="Invalid skill id"):
                await store.create(Skill(id="Bad Id", name="X"))

    @pytest.mark.asyncio
    async def test_update_changes_content_and_metadata(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="upd", name="Old", description="d", content="old"))
            updated = await store.update("upd", {"name": "New", "content": "new body", "tags": ["t2"]})
        assert updated.name == "New"
        assert updated.content == "new body"
        assert updated.tags == ["t2"]
        # File was rewritten
        full = store._skills_dir / "upd" / "skill.md"
        assert "name: New" in full.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_delete_removes_file_and_db_row(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="del", name="X"))
            assert store.get("del") is not None
            full = store._skills_dir / "del" / "skill.md"
            assert full.exists()
            ok = await store.delete("del")
        assert ok is True
        assert store.get("del") is None
        assert not full.exists()

    @pytest.mark.asyncio
    async def test_delete_unknown_id_returns_false(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            ok = await store.delete("nope")
        assert ok is False


# ── SkillStore — toggle, reorder ─────────────────────────────────────────────

class TestSkillStoreToggle:
    @pytest.mark.asyncio
    async def test_toggle_flips_enabled(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="toggle-1", name="T"))
            assert store.get("toggle-1").enabled is True
            await store.toggle("toggle-1")
            assert store.get("toggle-1").enabled is False
            await store.toggle("toggle-1")
            assert store.get("toggle-1").enabled is True

    @pytest.mark.asyncio
    async def test_toggle_unknown_id(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            ok = await store.toggle("nope")
        assert ok is False

    @pytest.mark.asyncio
    async def test_reorder_sets_order_indices(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="rank-one"))
            await store.create(Skill(id="rank-two"))
            await store.create(Skill(id="rank-three"))
            await store.reorder(["rank-three", "rank-one", "rank-two"])
        assert store.get("rank-three").order == 0
        assert store.get("rank-one").order == 1
        assert store.get("rank-two").order == 2


# ── SkillStore — filter (active_groups + enabled) ───────────────────────────

class TestSkillStoreFilter:
    @pytest.mark.asyncio
    async def test_get_enabled_for_active_groups_matches(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="skill-dev", groups=["dev"]))
            await store.create(Skill(id="skill-creative", groups=["creative"]))
            await store.create(Skill(id="skill-anywhere", groups=[]))  # empty = always
            await store.set_active_groups(["dev"])
            enabled = store.get_enabled_for_active_groups()
        ids = [s.id for s in enabled]
        assert "skill-dev" in ids
        assert "skill-anywhere" in ids  # empty groups = always included
        assert "skill-creative" not in ids

    @pytest.mark.asyncio
    async def test_disabled_excluded(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="skill-dev", groups=["dev"]))
            await store.toggle("skill-dev")  # disable
            enabled = store.get_enabled_for_active_groups()
        ids = [s.id for s in enabled]
        assert "skill-dev" not in ids

    @pytest.mark.asyncio
    async def test_missing_excluded(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="skill-ghost"))
            full = store._skills_dir / "skill-ghost" / "skill.md"
            if full.exists():
                full.unlink()
            await store.refresh_from_disk()
            enabled = store.get_enabled_for_active_groups()
        ids = [s.id for s in enabled]
        assert "skill-ghost" not in ids
        assert store.get("skill-ghost").missing is True

    @pytest.mark.asyncio
    async def test_filter_returns_sorted_by_order(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="aaa-skill", order=2))
            await store.create(Skill(id="bbb-skill", order=3))
            await store.create(Skill(id="ccc-skill", order=4))
            enabled = store.get_enabled_for_active_groups()
        ids = [s.id for s in enabled]
        assert ids.index("aaa-skill") < ids.index("bbb-skill") < ids.index("ccc-skill")


# ── SkillStore — groups / tags management ───────────────────────────────────

class TestSkillStoreGroupsAndTags:
    @pytest.mark.asyncio
    async def test_get_groups_returns_count_and_active(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="multi-group", groups=["dev", "creative"]))
            await store.create(Skill(id="dev-only", groups=["dev"]))
            await store.set_active_groups(["dev"])
            groups = store.get_groups()
        by_name = {g["name"]: g for g in groups}
        assert by_name["default"]["skill_count"] >= 2  # seeded skills
        assert by_name["dev"]["skill_count"] == 2
        assert by_name["dev"]["is_active"] is True
        assert by_name["creative"]["is_active"] is False

    @pytest.mark.asyncio
    async def test_get_tags(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="tag-rich", tags=["x", "y"]))
            await store.create(Skill(id="tag-x-only", tags=["x"]))
            tags = store.get_tags()
        by_name = {t["name"]: t for t in tags}
        assert by_name["x"]["skill_count"] == 2
        assert by_name["y"]["skill_count"] == 1

    @pytest.mark.asyncio
    async def test_rename_tag_updates_all_skills(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="old-1", tags=["old"]))
            await store.create(Skill(id="old-2", tags=["old", "other"]))
            await store.rename_tag("old", "new")
        assert store.get("old-1").tags == ["new"]
        assert store.get("old-2").tags == ["new", "other"]

    @pytest.mark.asyncio
    async def test_rename_group_propagates_to_skills(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="dev-skill", groups=["dev"]))
            await store.set_active_groups(["dev"])
            await store.rename_group("dev", "development")
        assert store.get("dev-skill").groups == ["development"]
        assert "development" in store._config.known_groups
        assert "development" in store._config.active_groups

    @pytest.mark.asyncio
    async def test_delete_group_resets_skill_to_default(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="temp-skill", groups=["temp"]))
            await store.delete_group("temp")
        assert store.get("temp-skill").groups == [DEFAULT_GROUP]

    @pytest.mark.asyncio
    async def test_cannot_delete_default_group(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            ok = await store.delete_group(DEFAULT_GROUP)
        assert ok is False


# ── SkillStore — refresh from disk ──────────────────────────────────────────

class TestSkillStoreRefresh:
    @pytest.mark.asyncio
    async def test_refresh_picks_up_new_file(self, store, mock_memory_store, workspace_dir):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            initial = len(store.list_all())
            # Add a new skill directory + file
            new_skill = workspace_dir / "skills" / "newcomer"
            new_skill.mkdir()
            (new_skill / "skill.md").write_text(
                "---\nname: Newcomer\ndescription: New on disk\n---\n\nbody\n",
                encoding="utf-8",
            )
            await store.refresh_from_disk()
            updated = store.list_all()
        assert len(updated) == initial + 1
        assert store.get("newcomer") is not None

    @pytest.mark.asyncio
    async def test_refresh_marks_missing(self, store, mock_memory_store, workspace_dir):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            await store.create(Skill(id="togo", name="X"))
            # Manually delete the file
            (workspace_dir / "skills" / "togo" / "skill.md").unlink()
            await store.refresh_from_disk()
        assert store.get("togo").missing is True

    @pytest.mark.asyncio
    async def test_load_is_idempotent(self, store, mock_memory_store):
        with patch("jarvis.services.skill_store.memory_store", mock_memory_store):
            await store.load()
            count1 = len(store.list_all())
            await store.load()
            count2 = len(store.list_all())
        assert count1 == count2


# ── Singleton ──────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_skill_store_returns_same_instance(self):
        s1 = get_skill_store()
        s2 = get_skill_store()
        assert s1 is s2
