"""
db.py — Database connection and core schema for the NYX client.

Handles connection management, schema initialisation, identity metadata,
and sync state. Contact operations live in contacts.py; message helpers
in messages.py.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


class DatabaseConnection:
    """
    Local SQLite database connection and core persistence helpers.

    Stores:
      - identity metadata (device_id, registered flag)
      - sync state (last_sync_time)

    NOTE: Messages are NOT persisted to the database. They live only in
    memory during the session (chat history is ephemeral by design).
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    # -- connection management ------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        """Open (or return existing) database connection and ensure schema."""
        if self._conn is not None:
            return self._conn

        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _init_schema(self) -> None:
        """Create tables if they do not exist; migrate for aliases."""
        conn = self._conn
        assert conn is not None

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS contacts (
                device_id   TEXT PRIMARY KEY,
                public_key  TEXT NOT NULL,
                alias       TEXT,
                cached_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        conn.commit()

        # Migrate older DBs that lack the alias column
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(contacts)").fetchall()
        }
        if "alias" not in cols:
            conn.execute("ALTER TABLE contacts ADD COLUMN alias TEXT")
            conn.commit()

    # -- identity helpers -----------------------------------------------------

    def is_registered(self) -> bool:
        """Return True if the device has been registered with the relay."""
        conn = self.connect()
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'registered'"
        ).fetchone()
        return row is not None and row["value"] == "1"

    def save_identity(self, device_id: str, public_key_b64: str) -> None:
        """Record that this device registered successfully."""
        conn = self.connect()
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('device_id', ?)",
            (device_id,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('public_key', ?)",
            (public_key_b64,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('registered', '1')"
        )
        conn.commit()

    def get_device_id(self) -> Optional[str]:
        """Return the stored device_id, or None."""
        conn = self.connect()
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'device_id'"
        ).fetchone()
        return row["value"] if row else None

    def get_public_key_b64(self) -> Optional[str]:
        """Return the stored public key, or None."""
        conn = self.connect()
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'public_key'"
        ).fetchone()
        return row["value"] if row else None

    # -- sync state -----------------------------------------------------------

    def get_last_sync_time(self) -> Optional[str]:
        """Return the ISO timestamp of the last sync, or None."""
        conn = self.connect()
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'last_sync_time'"
        ).fetchone()
        return row["value"] if row else None

    def set_last_sync_time(self, timestamp: str) -> None:
        """Store the ISO timestamp of the last successful sync."""
        conn = self.connect()
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_sync_time', ?)",
            (timestamp,),
        )
        conn.commit()