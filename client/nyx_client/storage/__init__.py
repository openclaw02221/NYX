"""
Storage layer.

Whitepaper: Local DB (SQLite) + Encrypted Cache + Config + Queue.
Sensitive columns encrypted at application layer (AEAD).
Extension point for SQLCipher when available.
"""

from nyx_client.storage.db import Database
from nyx_client.storage.profile import ProfileStore, derive_profile_key_from_passphrase
from nyx_client.storage.messages import MessageStore, StoredMessage
from nyx_client.storage.contacts import ContactStore, Contact
from nyx_client.storage.user_prefs import UserPrefs, UserProfile
from nyx_client.storage.rooms import RoomStore, Room

# Backward compatibility alias
ContactStorage = ContactStore

# NYXDatabase facade for compatibility
class NYXDatabase:
    def __init__(self, db_path: str = ":memory:"):
        self.db = Database(db_path)
        self.contacts = ContactStore(self.db)
        self.messages = MessageStore(self.db)
        self.rooms = RoomStore(self.db)
        self.profile = ProfileStore(self.db)

__all__ = [
    "Database",
    "NYXDatabase",
    "ProfileStore",
    "derive_profile_key_from_passphrase",
    "MessageStore",
    "StoredMessage",
    "ContactStore",
    "ContactStorage",
    "Contact",
    "UserPrefs",
    "UserProfile",
    "RoomStore",
    "Room",
]
