"""
Async SQLite client for logging conversations and messages.
"""

import datetime
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite


class SQLiteClient:
    """Lightweight wrapper around aiosqlite for conversation storage."""

    def __init__(self, db_path: str = "data/conversations.db") -> None:
        self.db_path = db_path
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Open a SQLite connection and ensure schema exists."""
        if self.conn:
            return

        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        await self.conn.execute("PRAGMA journal_mode=WAL;")
        await self._initialize_schema()

    async def _initialize_schema(self) -> None:
        """Create required tables if they don't exist."""
        assert self.conn is not None

        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                session_id TEXT PRIMARY KEY,
                status TEXT,
                issue_type TEXT,
                sentiment TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )

        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                message_id TEXT,
                customer_email TEXT,
                message_type TEXT,
                content TEXT,
                metadata TEXT,
                created_at TEXT
            )
            """
        )

        await self.conn.commit()

    async def close(self) -> None:
        """Close the SQLite connection."""
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def _ensure_connected(self) -> None:
        """Ensure a connection is available."""
        if self.conn is None:
            await self.connect()

    # Generic helpers
    async def execute(self, query: str, params: Tuple[Any, ...] = ()) -> None:
        """Execute a write query."""
        await self._ensure_connected()
        assert self.conn is not None
        await self.conn.execute(query, params)
        await self.conn.commit()

    async def fetch_one(self, query: str, params: Tuple[Any, ...] = ()) -> Optional[aiosqlite.Row]:
        """Fetch a single row."""
        await self._ensure_connected()
        assert self.conn is not None
        cursor = await self.conn.execute(query, params)
        row = await cursor.fetchone()
        await cursor.close()
        return row

    async def fetch_all(self, query: str, params: Tuple[Any, ...] = ()) -> List[aiosqlite.Row]:
        """Fetch all rows."""
        await self._ensure_connected()
        assert self.conn is not None
        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return rows

    # Domain-specific helpers
    async def add_message(
        self,
        session_id: str,
        message_id: str,
        customer_email: str,
        message_type: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert a conversation message."""
        await self._ensure_connected()
        assert self.conn is not None

        created_at = datetime.datetime.utcnow().isoformat()
        metadata_json = json.dumps(metadata or {})

        await self.conn.execute(
            """
            INSERT INTO messages (session_id, message_id, customer_email, message_type, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, message_id, customer_email, message_type, content, metadata_json, created_at),
        )
        await self.conn.commit()

    async def update_conversation(
        self,
        session_id: str,
        status: str = "active",
        issue_type: Optional[str] = None,
        sentiment: Optional[str] = None,
    ) -> None:
        """Upsert a conversation summary row."""
        await self._ensure_connected()
        assert self.conn is not None

        now = datetime.datetime.utcnow().isoformat()

        await self.conn.execute(
            """
            INSERT INTO conversations (session_id, status, issue_type, sentiment, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                status=excluded.status,
                issue_type=excluded.issue_type,
                sentiment=excluded.sentiment,
                updated_at=excluded.updated_at
            """,
            (session_id, status, issue_type, sentiment, now, now),
        )
        await self.conn.commit()

    async def health_check(self) -> Dict[str, Any]:
        """Perform a simple health check."""
        try:
            await self._ensure_connected()
            assert self.conn is not None
            cursor = await self.conn.execute("SELECT 1")
            await cursor.fetchone()
            await cursor.close()
            return {"status": "healthy", "test_passed": True, "database": self.db_path}
        except Exception as exc:  # pragma: no cover
            return {"status": "unhealthy", "test_passed": False, "error": str(exc)}


# Module-level singleton helpers
sqlite_client = SQLiteClient()


async def get_sqlite_client() -> SQLiteClient:
    """Return a connected SQLite client."""
    if sqlite_client.conn is None:
        await sqlite_client.connect()
    return sqlite_client


async def init_sqlite(db_path: str = "data/conversations.db") -> SQLiteClient:
    """Initialize SQLite client with custom path."""
    global sqlite_client
    sqlite_client = SQLiteClient(db_path=db_path)
    await sqlite_client.connect()
    return sqlite_client

