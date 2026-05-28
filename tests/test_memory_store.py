# tests/test_memory_store.py
"""测试记忆存储"""
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, AsyncMock
from jarvis.core.memory_store import SQLiteMemoryRepository, MemoryStore


class TestSQLiteMemoryRepository:
    """测试 SQLite 记忆仓储"""

    @pytest.fixture
    def temp_db(self):
        """创建临时数据库"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        yield db_path
        # 清理
        try:
            os.unlink(db_path)
        except:
            pass

    @pytest.fixture
    def repo(self, temp_db):
        """创建仓储实例"""
        return SQLiteMemoryRepository(temp_db)

    @pytest.mark.asyncio
    async def test_save_and_get_memory(self, repo):
        """测试保存和获取记忆"""
        await repo.save("test_key", "Test content", {"meta": "data"})
        result = await repo.get("test_key")
        assert result is not None
        assert result["key"] == "test_key"
        assert result["content"] == "Test content"
        assert result["metadata"]["meta"] == "data"

    @pytest.mark.asyncio
    async def test_retrieve_memory(self, repo):
        """测试检索记忆"""
        await repo.save("apple_key", "Apple is a fruit")
        await repo.save("banana_key", "Banana is a fruit")
        await repo.save("car_key", "Car is a vehicle")

        results = await repo.retrieve("fruit", top_k=2)
        assert len(results) <= 2
        # content LIKE '%fruit%' should match "Apple is a fruit" and "Banana is a fruit"
        assert any("fruit" in r["content"].lower() for r in results)

    @pytest.mark.asyncio
    async def test_delete_memory(self, repo):
        """测试删除记忆"""
        await repo.save("delete_key", "Will be deleted")
        result = await repo.get("delete_key")
        assert result is not None

        await repo.delete("delete_key")
        result = await repo.get("delete_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_conversation(self, repo):
        """测试保存对话"""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
        success = await repo.save_conversation("conv_1", "user_1", messages, {})
        assert success is True

        # 验证保存
        conv = await repo.get_conversation("conv_1")
        assert conv is not None
        assert conv["conversation_id"] == "conv_1"
        assert conv["user_id"] == "user_1"
        assert len(conv["messages"]) == 2

    @pytest.mark.asyncio
    async def test_get_conversation(self, repo):
        """测试获取对话"""
        messages = [{"role": "user", "content": "Test"}]
        await repo.save_conversation("conv_test", "test_user", messages, {"key": "value"})

        conv = await repo.get_conversation("conv_test")
        assert conv is not None
        assert conv["conversation_id"] == "conv_test"
        assert conv["user_id"] == "test_user"
        assert len(conv["messages"]) == 1
        assert conv["context"]["key"] == "value"

    @pytest.mark.asyncio
    async def test_get_nonexistent_conversation(self, repo):
        """测试获取不存在的对话"""
        conv = await repo.get_conversation("nonexistent_conv")
        assert conv is None

    @pytest.mark.asyncio
    async def test_list_conversations(self, repo):
        """测试列出对话"""
        await repo.save_conversation("conv_1", "user_1", [], {})
        await repo.save_conversation("conv_2", "user_2", [], {})
        await repo.save_conversation("conv_3", "user_1", [], {})

        convs = await repo.list_conversations(limit=10)
        assert len(convs) >= 3

    @pytest.mark.asyncio
    async def test_delete_conversation(self, repo):
        """测试删除对话"""
        await repo.save_conversation("conv_del", "user_1", [], {})
        conv = await repo.get_conversation("conv_del")
        assert conv is not None

        await repo.delete_conversation("conv_del")
        conv = await repo.get_conversation("conv_del")
        assert conv is None

    @pytest.mark.asyncio
    async def test_save_and_get_setting(self, repo):
        """测试保存和获取设置"""
        # save_setting 会自动 json.dumps() 存储，所以传入普通值
        await repo.save_setting("theme", "dark")
        value = await repo.get_setting("theme")
        # get_setting 会自动 json.loads() 返回，所以直接比较值
        assert value == "dark"

    @pytest.mark.asyncio
    async def test_get_all_settings(self, repo):
        """测试获取所有设置"""
        await repo.save_setting("key1", "value1")
        await repo.save_setting("key2", "value2")

        all_settings = await repo.get_all_settings()
        assert "key1" in all_settings
        assert "key2" in all_settings
        assert all_settings["key1"] == "value1"


class TestMemoryStore:
    """测试 MemoryStore 门面"""

    @pytest.fixture
    def store(self):
        """创建 MemoryStore 实例"""
        return MemoryStore()

    @pytest.mark.asyncio
    async def test_save_conversation_delegates_to_sqlite(self, store):
        """测试 save_conversation 委托给 SQLite"""
        with patch.object(store.sqlite_repo, 'save_conversation', new_callable=AsyncMock, return_value=True) as mock:
            result = await store.save_conversation("id", "uid", [], {})
            assert result is True
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_conversation_delegates_to_sqlite(self, store):
        """测试 get_conversation 委托给 SQLite"""
        with patch.object(store.sqlite_repo, 'get_conversation', new_callable=AsyncMock, return_value={"id": "test"}) as mock:
            result = await store.get_conversation("test_id")
            assert result["id"] == "test"
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_setting_delegates_to_sqlite(self, store):
        """测试 save_setting 委托给 SQLite"""
        with patch.object(store.sqlite_repo, 'save_setting', new_callable=AsyncMock, return_value=True) as mock:
            result = await store.save_setting("key", "value")
            assert result is True
            mock.assert_called_once_with("key", "value")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])