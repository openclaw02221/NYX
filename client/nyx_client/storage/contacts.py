"""
contacts.py — Contact operations for the NYX client local database.

Provides mixin methods for saving, resolving, and listing contacts
with optional aliases.
"""

from __future__ import annotations

from typing import List, Optional, Tuple


class ContactsMixin:
    """
    Contact CRUD and resolution helpers.

    Expects the host class to provide ``connect()`` returning a
    sqlite3.Connection with row_factory = sqlite3.Row.
    """

    def save_contact(
        self,
        device_id: str,
        public_key: str,
        alias: Optional[str] = None,
    ) -> None:
        """
        Cache a contact's public key locally.

        If alias is provided, it is set/updated.
        If alias is None on update, the existing alias is preserved.
        """
        conn = self.connect()  # type: ignore[attr-defined]
        if alias is not None:
            conn.execute(
                """
                INSERT INTO contacts (device_id, public_key, alias, cached_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(device_id) DO UPDATE SET
                    public_key = excluded.public_key,
                    alias      = excluded.alias,
                    cached_at  = excluded.cached_at
                """,
                (device_id, public_key, alias),
            )
        else:
            # Preserve existing alias on public-key-only updates
            conn.execute(
                """
                INSERT INTO contacts (device_id, public_key, alias, cached_at)
                VALUES (?, ?, NULL, datetime('now'))
                ON CONFLICT(device_id) DO UPDATE SET
                    public_key = excluded.public_key,
                    cached_at  = excluded.cached_at
                """,
                (device_id, public_key),
            )
        conn.commit()

    def update_alias(self, device_id: str, alias: Optional[str]) -> bool:
        """
        Set or clear the alias for a contact.
        Returns True if the contact exists and was updated.
        """
        conn = self.connect()  # type: ignore[attr-defined]
        # Resolve prefix if needed
        resolved = self.resolve_contact(device_id)
        if not resolved:
            return False
        # Empty string clears the alias
        alias_val = alias.strip() if alias and alias.strip() else None
        cur = conn.execute(
            "UPDATE contacts SET alias = ? WHERE device_id = ?",
            (alias_val, resolved),
        )
        conn.commit()
        return cur.rowcount > 0

    def get_contact(self, device_id: str) -> Optional[str]:
        """Return the cached public key for a device_id, or None."""
        conn = self.connect()  # type: ignore[attr-defined]
        row = conn.execute(
            "SELECT public_key FROM contacts WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        return row["public_key"] if row else None

    def get_contact_alias(self, device_id: str) -> Optional[str]:
        """Return the alias for a device_id, or None."""
        conn = self.connect()  # type: ignore[attr-defined]
        row = conn.execute(
            "SELECT alias FROM contacts WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if row and row["alias"]:
            return row["alias"]
        return None

    def get_contacts(
        self,
        sort_by: str = "id",
    ) -> List[Tuple[str, str, Optional[str]]]:
        """
        Return all known contacts as (device_id, public_key, alias) tuples.

        sort_by: 'id' (default) or 'alias'
        """
        conn = self.connect()  # type: ignore[attr-defined]
        if sort_by == "alias":
            order = "ORDER BY CASE WHEN alias IS NULL OR alias = '' THEN 1 ELSE 0 END, lower(alias), device_id"
        else:
            order = "ORDER BY device_id"
        rows = conn.execute(
            f"SELECT device_id, public_key, alias FROM contacts {order}"
        ).fetchall()
        return [(r["device_id"], r["public_key"], r["alias"]) for r in rows]

    def resolve_contact(self, name_or_id: str) -> Optional[str]:
        """
        Resolve a name/alias/prefix to a full device_id.

        Resolution order:
          1. Exact device_id match
          2. Exact alias match (case-insensitive)
          3. Unique device_id prefix match
          4. Unique alias prefix match (case-insensitive)
        """
        if not name_or_id:
            return None

        conn = self.connect()  # type: ignore[attr-defined]
        needle = name_or_id.strip()

        # 1. Exact device_id
        row = conn.execute(
            "SELECT device_id FROM contacts WHERE device_id = ?",
            (needle,),
        ).fetchone()
        if row:
            return row["device_id"]

        # 2. Exact alias (case-insensitive)
        row = conn.execute(
            "SELECT device_id FROM contacts WHERE lower(alias) = lower(?)",
            (needle,),
        ).fetchone()
        if row:
            return row["device_id"]

        # 3. Unique device_id prefix
        rows = conn.execute(
            "SELECT device_id FROM contacts WHERE device_id LIKE ?",
            (needle + "%",),
        ).fetchall()
        if len(rows) == 1:
            return rows[0]["device_id"]
        if len(rows) > 1:
            return None  # ambiguous

        # 4. Unique alias prefix (case-insensitive)
        rows = conn.execute(
            "SELECT device_id FROM contacts WHERE lower(alias) LIKE lower(?)",
            (needle + "%",),
        ).fetchall()
        if len(rows) == 1:
            return rows[0]["device_id"]

        return None

    def display_name(self, device_id: str) -> str:
        """
        Return the best display name for a contact: alias if set, else
        the first 16 chars of device_id.
        """
        alias = self.get_contact_alias(device_id)
        if alias:
            return alias
        return device_id[:16] if device_id else "???"