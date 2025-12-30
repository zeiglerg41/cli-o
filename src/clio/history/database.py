"""SQLite database for conversation history."""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import json
import logging

logger = logging.getLogger(__name__)


class HistoryDatabase:
    """Manages conversation history in SQLite database."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database. Defaults to ~/.clio/history.db
        """
        if db_path is None:
            db_path = Path.home() / ".clio" / "history.db"

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row  # Return rows as dicts
        self._init_schema()

        # Initialize RAG retriever (optional - gracefully degrades if unavailable)
        self._rag_retriever = None
        try:
            from ..rag.retriever import ContextRetriever
            self._rag_retriever = ContextRetriever()
            logger.info("RAG features enabled")
        except ImportError:
            logger.info("RAG features not available (sentence-transformers not installed)")
        except Exception as e:
            logger.warning(f"Failed to initialize RAG: {e}")

    def _init_schema(self):
        """Create database schema if not exists."""
        cursor = self.conn.cursor()

        # Conversations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL,
                end_time TEXT,
                working_dir TEXT,
                model TEXT,
                provider TEXT,
                starred INTEGER DEFAULT 0,
                title TEXT,
                message_count INTEGER DEFAULT 0
            )
        """)

        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls TEXT,
                tokens INTEGER,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)

        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_start_time
            ON conversations(start_time DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_msg_conv_id
            ON messages(conversation_id)
        """)

        self.conn.commit()

    def create_conversation(self, working_dir: str, model: str, provider: str, title: Optional[str] = None) -> int:
        """Create a new conversation.

        Args:
            working_dir: Current working directory
            model: Model name being used
            provider: Provider name
            title: Optional conversation title

        Returns:
            Conversation ID
        """
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()

        cursor.execute("""
            INSERT INTO conversations (start_time, working_dir, model, provider, title)
            VALUES (?, ?, ?, ?, ?)
        """, (now, working_dir, model, provider, title))

        self.conn.commit()
        return cursor.lastrowid

    def add_message(self, conversation_id: int, role: str, content: Optional[str] = None,
                    tool_calls: Optional[str] = None, tokens: Optional[int] = None):
        """Add a message to a conversation.

        Args:
            conversation_id: ID of the conversation
            role: Message role (user/assistant/system/tool)
            content: Message content (defaults to empty string if None)
            tool_calls: JSON string of tool calls if any
            tokens: Token count if available
        """
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()

        # Default to empty string if content is None (e.g., when only tool calls present)
        if content is None:
            content = ""

        cursor.execute("""
            INSERT INTO messages (conversation_id, timestamp, role, content, tool_calls, tokens)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (conversation_id, now, role, content, tool_calls, tokens))

        # Update message count
        cursor.execute("""
            UPDATE conversations
            SET message_count = message_count + 1,
                end_time = ?
            WHERE id = ?
        """, (now, conversation_id))

        # Auto-generate title from first user message
        if role == "user" and content:
            # Check if this conversation has a title
            cursor.execute("SELECT title, message_count FROM conversations WHERE id = ?", (conversation_id,))
            row = cursor.fetchone()
            if row and not row[0]:  # No title yet
                # Use first 60 chars of first user message as title
                title = content.strip()[:60]
                if len(content) > 60:
                    title += "..."
                cursor.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))

        self.conn.commit()

        # Add to RAG vector store if available (user and assistant messages only)
        if self._rag_retriever and content and role in ["user", "assistant"]:
            try:
                message_id = cursor.lastrowid
                self._rag_retriever.add_message(conversation_id, message_id, role, content)
            except Exception as e:
                # Don't fail the whole operation if RAG fails
                logger.warning(f"Failed to add message to RAG: {e}")

    def get_recent_conversations(self, limit: int = 20, include_starred: bool = True) -> List[Dict]:
        """Get most recent conversations.

        Args:
            limit: Number of conversations to return
            include_starred: If True, starred conversations are always included

        Returns:
            List of conversation dictionaries
        """
        cursor = self.conn.cursor()

        if include_starred:
            # Get all starred conversations plus recent non-starred
            cursor.execute("""
                SELECT * FROM conversations
                WHERE starred = 1
                UNION
                SELECT * FROM (
                    SELECT * FROM conversations
                    WHERE starred = 0
                    ORDER BY start_time DESC
                    LIMIT ?
                )
                ORDER BY start_time DESC
            """, (limit,))
        else:
            cursor.execute("""
                SELECT * FROM conversations
                ORDER BY start_time DESC
                LIMIT ?
            """, (limit,))

        return [dict(row) for row in cursor.fetchall()]

    def get_conversation_messages(self, conversation_id: int) -> List[Dict]:
        """Get all messages from a conversation.

        Args:
            conversation_id: Conversation ID

        Returns:
            List of message dictionaries
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY timestamp ASC
        """, (conversation_id,))

        return [dict(row) for row in cursor.fetchall()]

    def star_conversation(self, conversation_id: int):
        """Mark a conversation as starred (keep forever).

        Args:
            conversation_id: Conversation ID
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE conversations SET starred = 1 WHERE id = ?
        """, (conversation_id,))
        self.conn.commit()

    def unstar_conversation(self, conversation_id: int):
        """Remove star from a conversation.

        Args:
            conversation_id: Conversation ID
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE conversations SET starred = 0 WHERE id = ?
        """, (conversation_id,))
        self.conn.commit()

    def cleanup_old_conversations(self, keep_recent: int = 20):
        """Delete conversations older than the N most recent (except starred).

        Args:
            keep_recent: Number of recent conversations to keep
        """
        cursor = self.conn.cursor()

        # Get IDs of conversations to keep (starred + recent)
        cursor.execute("""
            SELECT DISTINCT id FROM (
                SELECT id, start_time FROM conversations WHERE starred = 1
                UNION
                SELECT id, start_time FROM conversations WHERE starred = 0
                ORDER BY start_time DESC
                LIMIT ?
            )
        """, (keep_recent,))

        keep_ids = [row[0] for row in cursor.fetchall()]

        if not keep_ids:
            return 0

        # Delete conversations not in keep list
        placeholders = ','.join('?' * len(keep_ids))
        cursor.execute(f"""
            DELETE FROM conversations
            WHERE id NOT IN ({placeholders})
        """, keep_ids)

        deleted_count = cursor.rowcount
        self.conn.commit()

        # Vacuum to reclaim space
        cursor.execute("VACUUM")

        return deleted_count

    def update_conversation_title(self, conversation_id: int, title: str):
        """Update conversation title.

        Args:
            conversation_id: Conversation ID
            title: New title
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE conversations SET title = ? WHERE id = ?
        """, (title, conversation_id))
        self.conn.commit()

    def retrieve_rag_context(
        self,
        conversation_id: int,
        query: str,
        n_results: int = 10,
        exclude_recent: int = 20
    ) -> List[Dict]:
        """Retrieve relevant context using RAG semantic search.

        Args:
            conversation_id: ID of the conversation
            query: Query text to find relevant context for
            n_results: Number of results to return
            exclude_recent: Exclude last N messages (they're sent verbatim)

        Returns:
            List of relevant message dicts
        """
        if not self._rag_retriever:
            logger.debug("RAG not available, returning empty context")
            return []

        try:
            return self._rag_retriever.retrieve_context(
                conversation_id, query, n_results, exclude_recent
            )
        except Exception as e:
            logger.warning(f"RAG retrieval failed: {e}")
            return []

    def close(self):
        """Close database connection."""
        self.conn.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
