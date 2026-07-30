"""
messages.py — Message storage helpers for the NYX client.

Messages are intentionally NOT persisted to the database (session-only
chat history by design). This module is reserved for future message
storage operations and currently provides no persistent API.
"""

from __future__ import annotations


class MessagesMixin:
    """
    Placeholder mixin for future message persistence.

    Chat history currently lives only in memory during a session
    (see nyx_client.core.messaging).
    """

    pass