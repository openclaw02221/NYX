"""
NYX Client Database Module.

Local SQLite storage for identity, contacts, and messages.
Consolidated from storage/db.py, storage/schema.py, storage/profile.py, 
storage/contacts.py, storage/messages.py.
"""

from __future__ import annotations

import sqlite3
import time
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from config import get_logger

log = get_logger(__name__)

SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_profile (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    identity_id     TEXT    NOT NULL UNIQUE,
    public_key      BLOB    NOT NULL,
    enc_identity_key BLOB   NOT NULL,
    enc_recovery_seed BLOB,
    display_name    TEXT,
    bio             TEXT,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    device_id       TEXT PRIMARY KEY,
    public_key      BLOB NOT NULL,
    enc_private_key BLOB NOT NULL,
    name            TEXT,
    created_at      INTEGER NOT NULL,
    revoked_at      INTEGER,
    last_seen_at    INTEGER
);

CREATE TABLE IF NOT EXISTS contacts (
    identity_id     TEXT PRIMARY KEY,
    public_key      BLOB,
    display_name    TEXT,
    notes           TEXT,
    trusted         INTEGER NOT NULL DEFAULT 0,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    type            TEXT NOT NULL DEFAULT 'dm',
    peer_id         TEXT,
    title           TEXT,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    last_sequence   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    message_id      TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    sender_id       TEXT NOT NULL,
    device_id       TEXT,
    payload         BLOB NOT NULL,
    signature       BLOB,
    previous_hash   TEXT,
    sequence        INTEGER NOT NULL,
    timestamp       INTEGER NOT NULL,
    direction       TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    status          TEXT NOT NULL DEFAULT 'sent',
    protocol_version INTEGER NOT NULL DEFAULT 3,
    created_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conv_seq
    ON messages(conversation_id, sequence);

CREATE INDEX IF NOT EXISTS idx_messages_conv_ts
    ON messages(conversation_id, timestamp);

CREATE TABLE IF NOT EXISTS session_state (
    key   TEXT PRIMARY KEY,
    value BLOB NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


@dataclass
class Message:
    """Message record."""
    message_id: str
    conversation_id: str
    sender_id: str
    payload: bytes
    sequence: int
    timestamp: int
    direction: str
    status: str = "sent"
    
    @property
    def id(self) -> str:
        """Alias for message_id for compatibility."""
        return self.message_id


class NYXDatabase:
    """SQLite database wrapper for NYX client."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        """Connect to database and ensure schema exists."""
        if self._conn is not None:
            return self._conn
        
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        
        self._conn = conn
        self._ensure_schema(conn)
        log.info("database.connected", path=str(self.path))
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """Initialize or verify database schema."""
        conn.executescript(SCHEMA_SQL)
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        
        if row is None:
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('created_at', ?)",
                (str(int(time.time())),),
            )
            log.info("database.schema_initialized", version=SCHEMA_VERSION)
        else:
            current = int(row["value"])
            if current != SCHEMA_VERSION:
                log.warning(
                    "database.schema_version_mismatch",
                    current=current,
                    expected=SCHEMA_VERSION,
                )

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            log.info("database.closed")

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a SQL statement."""
        return self.connect().execute(sql, params)

    def executemany(self, sql: str, seq: list) -> sqlite3.Cursor:
        """Execute a SQL statement multiple times."""
        return self.connect().executemany(sql, seq)

    def commit(self) -> None:
        """Commit current transaction."""
        if self._conn:
            self._conn.commit()

    # Identity operations
    def save_identity(self, identity_id: str, public_key: bytes, 
                     enc_private_key: bytes) -> None:
        """Save identity to database."""
        now = int(time.time())
        self.execute(
            """INSERT OR REPLACE INTO identity_profile 
               (id, identity_id, public_key, enc_identity_key, created_at, updated_at)
               VALUES (1, ?, ?, ?, ?, ?)""",
            (identity_id, public_key, enc_private_key, now, now)
        )
        self.commit()
        log.info("database.identity_saved", identity=identity_id)

    def load_identity(self) -> Optional[Dict[str, Any]]:
        """Load identity from database."""
        row = self.execute(
            "SELECT * FROM identity_profile WHERE id = 1"
        ).fetchone()
        if row:
            return dict(row)
        return None

    # Contact operations
    def save_contact(self, identity_id: str, display_name: str = "", 
                     public_key: Optional[bytes] = None) -> None:
        """Save or update a contact."""
        now = int(time.time())
        self.execute(
            """INSERT OR REPLACE INTO contacts 
               (identity_id, display_name, public_key, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (identity_id, display_name, public_key, now, now)
        )
        self.commit()

    def get_contact(self, identity_id: str) -> Optional[Dict[str, Any]]:
        """Get contact by identity ID."""
        row = self.execute(
            "SELECT * FROM contacts WHERE identity_id = ?",
            (identity_id,)
        ).fetchone()
        if row:
            return dict(row)
        return None

    def list_contacts(self) -> List[Dict[str, Any]]:
        """List all contacts."""
        rows = self.execute("SELECT * FROM contacts ORDER BY display_name").fetchall()
        return [dict(row) for row in rows]

    # Message operations
    def save_message(self, message: Message) -> None:
        """Save a message to database."""
        now = int(time.time())
        self.execute(
            """INSERT INTO messages 
               (message_id, conversation_id, sender_id, payload, sequence, 
                timestamp, direction, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (message.message_id, message.conversation_id, message.sender_id,
             message.payload, message.sequence, message.timestamp,
             message.direction, message.status, now)
        )
        self.commit()

    def get_messages(self, conversation_id: str, limit: int = 50) -> List[Message]:
        """Get messages for a conversation."""
        rows = self.execute(
            """SELECT * FROM messages 
               WHERE conversation_id = ? 
               ORDER BY sequence DESC 
               LIMIT ?""",
            (conversation_id, limit)
        ).fetchall()
        
        messages = []
        for row in rows:
            messages.append(Message(
                message_id=row["message_id"],
                conversation_id=row["conversation_id"],
                sender_id=row["sender_id"],
                payload=row["payload"],
                sequence=row["sequence"],
                timestamp=row["timestamp"],
                direction=row["direction"],
                status=row["status"],
            ))
        return list(reversed(messages))

    # Conversation operations
    def ensure_conversation(self, conversation_id: str, peer_id: str) -> None:
        """Ensure a conversation exists."""
        now = int(time.time())
        self.execute(
            """INSERT OR IGNORE INTO conversations 
               (conversation_id, peer_id, created_at, updated_at)
               VALUES (?, ?, ?, ?)""",
            (conversation_id, peer_id, now, now)
        )
        self.commit()

    def list_conversations(self) -> List[Dict[str, Any]]:
        """List all conversations."""
        rows = self.execute(
            """SELECT * FROM conversations 
               ORDER BY updated_at DESC"""
        ).fetchall()
        return [dict(row) for row in rows]

    def save_profile(self, display_name: str, bio: str) -> None:
        """Update local user profile."""
        now = int(time.time())
        self.execute(
            """UPDATE identity_profile 
               SET display_name = ?, bio = ?, updated_at = ?
               WHERE id = 1""",
            (display_name, bio, now)
        )
        self.commit()

    # Additional methods needed by ui.py
    def get_all_contacts(self) -> List[Dict[str, Any]]:
        """Get all contacts with additional fields for UI."""
        contacts = self.list_contacts()
        # Add 'name' field as alias for display_name
        for contact in contacts:
            contact['name'] = contact.get('display_name', '') or contact['identity_id'][:16]
        return contacts

    def get_all_groups(self) -> List[Dict[str, Any]]:
        """Get all group conversations."""
        rows = self.execute(
            """SELECT * FROM conversations 
               WHERE type = 'group' 
               ORDER BY updated_at DESC"""
        ).fetchall()
        groups = [dict(row) for row in rows]
        # Ensure room_id field exists (alias for conversation_id)
        for group in groups:
            if 'room_id' not in group:
                group['room_id'] = group['conversation_id']
        return groups

    def get_messages_with_contact(self, identity_id: str) -> List[Dict[str, Any]]:
        """Get all messages with a specific contact."""
        # Find conversation with this contact
        row = self.execute(
            """SELECT conversation_id FROM conversations 
               WHERE peer_id = ? AND type = 'dm'""",
            (identity_id,)
        ).fetchone()
        
        if not row:
            return []
        
        conversation_id = row['conversation_id']
        rows = self.execute(
            """SELECT * FROM messages 
               WHERE conversation_id = ? 
               ORDER BY sequence ASC""",
            (conversation_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def get_group_messages(self, room_id: str) -> List[Dict[str, Any]]:
        """Get all messages in a group."""
        rows = self.execute(
            """SELECT * FROM messages 
               WHERE conversation_id = ? 
               ORDER BY sequence ASC""",
            (room_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_contact(self, identity_id: str) -> None:
        """Delete a contact and associated conversations/messages."""
        # Find conversations with this contact
        rows = self.execute(
            """SELECT conversation_id FROM conversations 
               WHERE peer_id = ? AND type = 'dm'""",
            (identity_id,)
        ).fetchall()
        
        for row in rows:
            conv_id = row['conversation_id']
            # Delete messages first
            self.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            # Delete conversation
            self.execute("DELETE FROM conversations WHERE conversation_id = ?", (conv_id,))
        
        # Delete contact
        self.execute("DELETE FROM contacts WHERE identity_id = ?", (identity_id,))
        self.commit()

    def delete_group(self, room_id: str) -> None:
        """Delete a group and all its messages."""
        self.execute("DELETE FROM messages WHERE conversation_id = ?", (room_id,))
        self.execute("DELETE FROM conversations WHERE conversation_id = ? AND type = 'group'", (room_id,))
        self.commit()

    def leave_group(self, room_id: str, user_identity_id: str) -> None:
        """Leave a group (delete locally)."""
        # For now, just delete the group locally
        self.delete_group(room_id)

    def delete_all_messages(self) -> None:
        """Delete all messages from database."""
        self.execute("DELETE FROM messages")
        self.commit()

    def delete_identity(self) -> None:
        """Delete the local identity."""
        self.execute("DELETE FROM identity_profile WHERE id = 1")
        self.commit()

    def create_identity(self) -> Dict[str, Any]:
        """Create a new identity and return it."""
        from crypto import Identity
        import random
        
        # Create new identity
        identity_obj = Identity.create()
        identity_id = identity_obj.id
        
        # Generate a random name
        adjectives = ['Swift', 'Brave', 'Silent', 'Wise', 'Bold', 'Quick']
        nouns = ['Fox', 'Wolf', 'Eagle', 'Hawk', 'Tiger', 'Bear']
        name = f"{random.choice(adjectives)}{random.choice(nouns)}"
        
        # Save to database
        now = int(time.time())
        self.execute(
            """INSERT INTO identity_profile 
               (id, identity_id, public_key, enc_identity_key, display_name, created_at, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?)""",
            (identity_id, identity_obj.public_key_bytes, 
             identity_obj.identity_key.private_bytes(), name, now, now)
        )
        self.commit()
        
        # Return identity data
        return {
            'identity_id': identity_id,
            'name': name,
            'public_key': identity_obj.public_key_bytes,
            'enc_identity_key': identity_obj.identity_key.private_bytes(),
            'created_at': now,
            'updated_at': now
        }
