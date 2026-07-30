"""
storage — Local SQLite storage for the NYX client.
"""

from nyx_client.storage.contacts import ContactsMixin
from nyx_client.storage.db import DatabaseConnection
from nyx_client.storage.messages import MessagesMixin


class NYXDatabase(ContactsMixin, MessagesMixin, DatabaseConnection):
    """
    Local SQLite database for NYX client persistence.

    Combines connection management, identity/sync state, and contact
    operations into a single interface matching the original NYXDatabase.
    """

    pass


__all__ = [
    "NYXDatabase",
    "DatabaseConnection",
    "ContactsMixin",
    "MessagesMixin",
]