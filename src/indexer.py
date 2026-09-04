"""Database schema and indexing pipeline for search-gpt."""

from __future__ import annotations

import glob
import sqlite3
import time
from pathlib import Path
from typing import Any, List, Optional

from src.parser import ParsedConversation, load_conversations_from_file

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "conversations.db"
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def get_db_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create and configure a SQLite connection with FTS5 and row factory."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize SQLite tables and FTS5 full-text search index."""
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                create_time REAL,
                update_time REAL,
                model TEXT,
                message_count INTEGER DEFAULT 0,
                source_file TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                create_time REAL,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conv_turn 
            ON messages (conversation_id, turn_index)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_create_time 
            ON conversations (create_time DESC)
        """)

        # FTS5 Virtual Table for full-text BM25 search
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                message_id UNINDEXED,
                conversation_id UNINDEXED,
                role UNINDEXED,
                title,
                content,
                tokenize = 'porter unicode61'
            )
        """)


def index_conversations(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    db_path: Path | str = DEFAULT_DB_PATH,
    reset: bool = True,
) -> dict[str, Any]:
    """Index all JSON files in data_dir into SQLite database."""
    start_time = time.time()
    db_path = Path(db_path)
    data_dir = Path(data_dir)

    if reset and db_path.exists():
        db_path.unlink()

    conn = get_db_connection(db_path)
    init_db(conn)

    json_files = sorted(glob.glob(str(data_dir / "*.json")))
    if not json_files:
        print(f"No JSON files found in {data_dir}")
        return {"conversations": 0, "messages": 0, "duration": 0.0}

    total_convs = 0
    total_messages = 0

    print(f"Indexing {len(json_files)} JSON files into {db_path}...")

    with conn:
        for file_path in json_files:
            file_convs: List[tuple] = []
            file_messages: List[tuple] = []
            file_fts_rows: List[tuple] = []

            for conv in load_conversations_from_file(file_path):
                total_convs += 1
                msg_count = len(conv.messages)
                total_messages += msg_count

                file_convs.append((
                    conv.id,
                    conv.title,
                    conv.create_time,
                    conv.update_time,
                    conv.model,
                    msg_count,
                    conv.source_file,
                ))

                for msg in conv.messages:
                    file_messages.append((
                        msg.id,
                        msg.conversation_id,
                        msg.turn_index,
                        msg.role,
                        msg.content,
                        msg.create_time,
                    ))

                    # Index both user and assistant text, plus title
                    if msg.content.strip():
                        file_fts_rows.append((
                            msg.id,
                            msg.conversation_id,
                            msg.role,
                            conv.title,
                            msg.content,
                        ))

            # Batch insert
            conn.executemany("""
                INSERT OR REPLACE INTO conversations (
                    id, title, create_time, update_time, model, message_count, source_file
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, file_convs)

            conn.executemany("""
                INSERT OR REPLACE INTO messages (
                    id, conversation_id, turn_index, role, content, create_time
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, file_messages)

            conn.executemany("""
                INSERT INTO messages_fts (
                    message_id, conversation_id, role, title, content
                ) VALUES (?, ?, ?, ?, ?)
            """, file_fts_rows)

            print(f"  ✓ {Path(file_path).name}: {len(file_convs)} conversations, {len(file_messages)} messages")

    # Run optimize on FTS5 index
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('optimize')")
    conn.close()

    duration = time.time() - start_time
    print(f"\nDone! Indexed {total_convs} conversations and {total_messages} messages in {duration:.2f}s.")
    return {
        "conversations": total_convs,
        "messages": total_messages,
        "duration": duration,
        "db_path": str(db_path),
    }


if __name__ == "__main__":
    index_conversations()
