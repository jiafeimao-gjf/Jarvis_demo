# jarvis/core/memory_store.py
"""记忆存储模块 - Repository Pattern 实现"""
import json
import sqlite3
from abc import ABC, abstractmethod
from typing import Optional, Any
from pathlib import Path
from datetime import datetime
import numpy as np

from jarvis.config import settings
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryRepository(ABC):
    """记忆仓储抽象接口（Repository Pattern）"""

    @abstractmethod
    async def save(self, key: str, content: str, metadata: dict = None) -> bool:
        """保存记忆"""
        pass

    @abstractmethod
    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """检索记忆"""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """删除记忆"""
        pass

    @abstractmethod
    async def get(self, key: str) -> Optional[dict]:
        """获取单条记忆"""
        pass


class SQLiteMemoryRepository(MemoryRepository):
    """基于 SQLite 的结构化记忆仓储"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.storage.sqlite_db_path
        self._init_table()

    def _init_table(self):
        """初始化表结构"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_key ON memories(key)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    messages TEXT,
                    context TEXT,
                    topic TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Migration: add topic column to existing DBs that pre-date it
            try:
                conn.execute("ALTER TABLE conversations ADD COLUMN topic TEXT")
            except Exception:
                pass  # column already exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info(f"SQLite memory store initialized at {self.db_path}")

    async def save(self, key: str, content: str, metadata: dict = None) -> bool:
        """保存记忆到 SQLite"""
        try:
            memory_id = f"{key}_{int(datetime.now().timestamp())}"
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO memories (memory_id, key, content, metadata)
                       VALUES (?, ?, ?, ?)""",
                    (memory_id, key, content, json.dumps(metadata or {}))
                )
            logger.debug(f"Saved memory: {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")
            return False

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """简单关键词检索（SQLite 不支持向量检索）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """SELECT * FROM memories
                       WHERE content LIKE ? OR key LIKE ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (f"%{query}%", f"%{query}%", top_k)
                )
                rows = cursor.fetchall()
                return [
                    {
                        "key": row["key"],
                        "content": row["content"],
                        "metadata": json.loads(row["metadata"]),
                        "score": 1.0  # SQLite 无向量分数
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to retrieve memory: {e}")
            return []

    async def delete(self, key: str) -> bool:
        """删除记忆"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM memories WHERE key = ?", (key,))
            return True
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return False

    async def get(self, key: str) -> Optional[dict]:
        """获取单条记忆"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM memories WHERE key = ? ORDER BY created_at DESC LIMIT 1",
                    (key,)
                )
                row = cursor.fetchone()
                if row:
                    return {
                        "key": row["key"],
                        "content": row["content"],
                        "metadata": json.loads(row["metadata"])
                    }
                return None
        except Exception as e:
            logger.error(f"Failed to get memory: {e}")
            return None

    async def save_conversation(self, conversation_id: str, user_id: str,
                               messages: list[dict], context: dict,
                               topic: Optional[str] = None) -> bool:
        """保存对话历史"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # If topic is provided, include it; otherwise preserve existing topic
                if topic is not None:
                    conn.execute(
                        """INSERT OR REPLACE INTO conversations
                           (conversation_id, user_id, messages, context, topic, updated_at)
                           VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                        (conversation_id, user_id, json.dumps(messages), json.dumps(context), topic)
                    )
                else:
                    conn.execute(
                        """INSERT OR REPLACE INTO conversations
                           (conversation_id, user_id, messages, context, updated_at)
                           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                        (conversation_id, user_id, json.dumps(messages), json.dumps(context))
                    )
            return True
        except Exception as e:
            logger.error(f"Failed to save conversation: {e}")
            return False

    async def update_conversation_topic(self, conversation_id: str, topic: Optional[str]) -> bool:
        """Update only the topic column (no re-serialization of messages)"""
        try:
            normalized = topic.strip()[:60] if topic else None
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """UPDATE conversations
                       SET topic = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE conversation_id = ?""",
                    (normalized, conversation_id)
                )
            return True
        except Exception as e:
            logger.error(f"Failed to update conversation topic: {e}")
            return False

    async def get_conversation(self, conversation_id: str) -> Optional[dict]:
        """获取对话历史"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM conversations WHERE conversation_id = ?",
                    (conversation_id,)
                )
                row = cursor.fetchone()
                if row:
                    return {
                        "conversation_id": row["conversation_id"],
                        "user_id": row["user_id"],
                        "topic": row["topic"],
                        "messages": json.loads(row["messages"]),
                        "context": json.loads(row["context"])
                    }
                return None
        except Exception as e:
            logger.error(f"Failed to get conversation: {e}")
            return None

    async def list_conversations(self, limit: int = 50) -> list[dict]:
        """列出所有对话（简要信息）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """SELECT conversation_id, user_id, messages, context, topic, created_at, updated_at
                       FROM conversations ORDER BY updated_at DESC LIMIT ?""",
                    (limit,)
                )
                rows = cursor.fetchall()
                return [
                    {
                        "conversation_id": row["conversation_id"],
                        "user_id": row["user_id"],
                        "topic": row["topic"],
                        "message_count": len(json.loads(row["messages"])),
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"]
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to list conversations: {e}")
            return []

    async def delete_conversation(self, conversation_id: str) -> bool:
        """删除对话"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
            return True
        except Exception as e:
            logger.error(f"Failed to delete conversation: {e}")
            return False

    async def save_setting(self, key: str, value: Any) -> bool:
        """保存设置到数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO settings (key, value, updated_at)
                       VALUES (?, ?, CURRENT_TIMESTAMP)""",
                    (key, json.dumps(value))
                )
            return True
        except Exception as e:
            logger.error(f"Failed to save setting: {e}")
            return False

    async def get_setting(self, key: str) -> Optional[Any]:
        """从数据库获取设置"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT value FROM settings WHERE key = ?",
                    (key,)
                )
                row = cursor.fetchone()
                if row:
                    return json.loads(row["value"])
                return None
        except Exception as e:
            logger.error(f"Failed to get setting: {e}")
            return None

    async def get_all_settings(self) -> dict:
        """获取所有设置"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT key, value FROM settings")
                rows = cursor.fetchall()
                return {row["key"]: json.loads(row["value"]) for row in rows}
        except Exception as e:
            logger.error(f"Failed to get all settings: {e}")
            return {}


# 简单向量嵌入实现（可替换为 proper embedding model）
async def simple_embed(text: str) -> list[float]:
    """简单文本嵌入（基于词频）"""
    words = text.lower().split()
    vector = np.zeros(512)
    for i, word in enumerate(words[:512]):
        vector[i % 512] += hash(word) % 1000 / 1000.0
    return vector.tolist()


class LanceDBMemoryRepository(MemoryRepository):
    """基于 LanceDB 的向量记忆仓储"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.storage.lance_db_path
        self._client = None
        self._table = None
        self._init_db()

    def _init_db(self):
        """初始化 LanceDB"""
        try:
            import lancedb
            self._client = lancedb.connect(str(self.db_path))
            # 检查表是否存在，不存在则创建
            table_names = self._client.table_names()
            if "memories" not in table_names:
                # 使用 pyarrow 定义 schema 以确保兼容性
                import pyarrow as pa
                schema = pa.schema([
                    ("vector", pa.list_(pa.float32(), 512)),
                    ("content", pa.string()),
                    ("key", pa.string()),
                    ("metadata", pa.string()),
                ])
                self._table = self._client.create_table("memories", schema=schema)
            else:
                self._table = self._client.open_table("memories")
            logger.info(f"LanceDB memory store initialized at {self.db_path}")
        except ImportError:
            logger.warning("LanceDB not installed, falling back to SQLite only")
            self._client = None
        except Exception as e:
            logger.warning(f"LanceDB init failed, falling back to SQLite only: {e}")
            self._client = None

    async def save(self, key: str, content: str, metadata: dict = None) -> bool:
        """保存记忆到 LanceDB"""
        if not self._client:
            return False
        try:
            vector = await simple_embed(content)
            self._table.add([
                {
                    "vector": vector,
                    "content": content,
                    "key": key,
                    "metadata": json.dumps(metadata or {})
                }
            ])
            logger.debug(f"Saved memory to LanceDB: {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to save memory to LanceDB: {e}")
            return False

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """向量相似度检索"""
        if not self._client:
            return []
        try:
            query_vector = await simple_embed(query)
            results = self._table.search(query_vector, top_k).to_list()
            return [
                {
                    "key": r["key"],
                    "content": r["content"],
                    "metadata": json.loads(r["metadata"]),
                    "score": 1.0 - r["_distance"]  # 转换距离为相似度
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Failed to retrieve from LanceDB: {e}")
            return []

    @staticmethod
    def _sanitize_key(key: str) -> str:
        """Sanitize key to prevent LanceDB filter injection"""
        return key.replace("'", "''")

    async def delete(self, key: str) -> bool:
        """删除记忆"""
        if not self._client:
            return False
        try:
            safe_key = self._sanitize_key(key)
            self._table.delete(f"key = '{safe_key}'")
            return True
        except Exception as e:
            logger.error(f"Failed to delete from LanceDB: {e}")
            return False

    async def get(self, key: str) -> Optional[dict]:
        """获取单条记忆"""
        if not self._client:
            return None
        try:
            safe_key = self._sanitize_key(key)
            results = self._table.search(f"key = '{safe_key}'").limit(1).to_list()
            if results:
                r = results[0]
                return {
                    "key": r["key"],
                    "content": r["content"],
                    "metadata": json.loads(r["metadata"])
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get from LanceDB: {e}")
            return None


class MemoryStore:
    """统一记忆存储接口（门面模式）"""

    def __init__(self):
        self.sqlite_repo = SQLiteMemoryRepository()
        self.lance_repo = LanceDBMemoryRepository()
        logger.info("MemoryStore initialized with SQLite + LanceDB")

    async def save(self, key: str, content: str, metadata: dict = None) -> bool:
        """同时保存到 SQLite 和 LanceDB"""
        sqlite_ok = await self.sqlite_repo.save(key, content, metadata)
        lance_ok = await self.lance_repo.save(key, content, metadata)
        return sqlite_ok and lance_ok

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """优先从 LanceDB 检索，退化为 SQLite"""
        results = await self.lance_repo.retrieve(query, top_k)
        if not results:
            results = await self.sqlite_repo.retrieve(query, top_k)
        return results

    async def save_conversation(self, conversation_id: str, user_id: str,
                               messages: list[dict], context: dict,
                               topic: Optional[str] = None) -> bool:
        """保存对话历史"""
        return await self.sqlite_repo.save_conversation(
            conversation_id, user_id, messages, context, topic
        )

    async def update_conversation_topic(self, conversation_id: str, topic: Optional[str]) -> bool:
        """更新对话主题（不重新序列化 messages）"""
        return await self.sqlite_repo.update_conversation_topic(conversation_id, topic)

    async def get_conversation(self, conversation_id: str) -> Optional[dict]:
        """获取对话历史"""
        return await self.sqlite_repo.get_conversation(conversation_id)

    async def list_conversations(self, limit: int = 50) -> list[dict]:
        """列出所有对话"""
        return await self.sqlite_repo.list_conversations(limit)

    async def delete_conversation(self, conversation_id: str) -> bool:
        """删除对话"""
        return await self.sqlite_repo.delete_conversation(conversation_id)

    async def save_setting(self, key: str, value: Any) -> bool:
        """保存设置"""
        return await self.sqlite_repo.save_setting(key, value)

    async def get_setting(self, key: str) -> Optional[Any]:
        """获取设置"""
        return await self.sqlite_repo.get_setting(key)

    async def get_all_settings(self) -> dict:
        """获取所有设置"""
        return await self.sqlite_repo.get_all_settings()


# 全局单例
memory_store = MemoryStore()