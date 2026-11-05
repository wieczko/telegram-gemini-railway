import re
import sqlite3
from pathlib import Path
from typing import TypedDict


class StoredMessage(TypedDict):
    id: int
    role: str
    content: str


def _connect(database_path: str) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def initialize(database_path: str) -> None:
    with _connect(database_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                turn_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS messages_user_id_id ON messages(user_id, id)"
        )
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content,
                user_id UNINDEXED,
                turn_id UNINDEXED,
                tokenize='unicode61'
            )
            """
        )


def save_message(
    database_path: str, user_id: int, turn_id: str, role: str, content: str
) -> None:
    with _connect(database_path) as connection:
        cursor = connection.execute(
            "INSERT INTO messages (user_id, turn_id, role, content) VALUES (?, ?, ?, ?)",
            (user_id, turn_id, role, content),
        )
        connection.execute(
            """
            INSERT INTO messages_fts (rowid, content, user_id, turn_id)
            VALUES (?, ?, ?, ?)
            """,
            (cursor.lastrowid, content, str(user_id), turn_id),
        )


def recent_messages(
    database_path: str, user_id: int, limit: int, exclude_turn_id: str
) -> list[StoredMessage]:
    with _connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, role, content
            FROM messages
            WHERE user_id = ? AND turn_id != ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, exclude_turn_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def relevant_messages(
    database_path: str,
    user_id: int,
    query: str,
    exclude_turn_id: str,
    recent_message_limit: int,
    turn_limit: int,
) -> list[StoredMessage]:
    terms = list(dict.fromkeys(re.findall(r"\w{2,}", query, flags=re.UNICODE)))[:12]
    if not terms:
        return []

    match_query = " OR ".join(f'"{term}"' for term in terms)
    with _connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT turn_id
            FROM messages_fts
            WHERE messages_fts MATCH ?
                AND user_id = ?
                AND turn_id != ?
                AND turn_id NOT IN (
                    SELECT DISTINCT turn_id
                    FROM (
                        SELECT turn_id
                        FROM messages
                        WHERE user_id = ? AND turn_id != ?
                        ORDER BY id DESC
                        LIMIT ?
                    )
                )
            ORDER BY bm25(messages_fts)
            LIMIT ?
            """,
            (
                match_query,
                str(user_id),
                exclude_turn_id,
                user_id,
                exclude_turn_id,
                recent_message_limit,
                turn_limit * 10,
            ),
        ).fetchall()
        turn_ids = list(dict.fromkeys(row["turn_id"] for row in rows))[:turn_limit]
        if not turn_ids:
            return []

        placeholders = ",".join("?" for _ in turn_ids)
        messages = connection.execute(
            f"""
            SELECT id, role, content
            FROM messages
            WHERE user_id = ? AND turn_id IN ({placeholders})
            ORDER BY id
            """,
            (user_id, *turn_ids),
        ).fetchall()
    return [dict(row) for row in messages]


def clear_user_history(database_path: str, user_id: int) -> None:
    with _connect(database_path) as connection:
        connection.execute(
            "DELETE FROM messages_fts WHERE user_id = ?", (str(user_id),)
        )
        connection.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
