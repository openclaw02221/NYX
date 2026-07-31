"""
Backend wrapper for TUI compatibility.

This class wraps NyxApp to provide the exact interface that tui.py expects.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any
import requests

from nyx_client.config.logging import get_logger
from nyx_client.core.app import NyxApp

log = get_logger(__name__)


class TUIBackend:
    """Adapter that provides the interface tui.py expects."""

    def __init__(self, app: NyxApp):
        self._app = app
        # Ensure app is started
        if not app._started:
            app.start()

    @property
    def identity(self) -> Any:
        """Return identity object with device_id and address properties."""
        return self._app.identity

    @property
    def connection(self) -> Any:
        """Return connection manager."""
        return ConnectionAdapter(self._app)

    @property
    def contacts(self) -> List[Dict[str, Any]]:
        """Return contacts as list of dicts."""
        if not self._app.contacts:
            return []
        try:
            contact_list = self._app.contacts.list_all()
            return [
                {
                    'device_id': c.identity_id,
                    'alias': c.display_name,
                    'public_key': c.public_key,
                }
                for c in contact_list
            ]
        except Exception as e:
            log.error("backend.contacts_list_failed", error=str(e))
            return []

    @property
    def storage(self) -> Any:
        """Return storage adapter."""
        return StorageAdapter(self._app)

    @property
    def messaging(self) -> Any:
        """Return messaging adapter."""
        return MessagingAdapter(self._app)

    @property
    def config(self) -> Any:
        """Return config adapter."""
        return ConfigAdapter(self._app)

    def load_contacts(self) -> None:
        """Load contacts (no-op since we read directly from DB)."""
        pass

    def sync(self) -> None:
        """Sync with server."""
        if self._app.connection:
            try:
                self._app.connection.sync_messages()
            except Exception as e:
                log.error("backend.sync_failed", error=str(e))

    def search_channels(self, query: str) -> List[Dict[str, Any]]:
        """Search for public channels."""
        endpoint = self._app.select_best_server()
        if not endpoint:
            return []
        
        try:
            url = f"{endpoint.rstrip('/')}/api/v3/channels/search"
            response = requests.get(url, params={'q': query}, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return data.get('channels', [])
        except Exception as e:
            log.debug("backend.search_channels_failed", error=str(e))
        
        return []

    def join_channel(self, channel_id: str) -> bool:
        """Join a channel."""
        if not self._app.identity:
            return False
        
        endpoint = self._app.select_best_server()
        if not endpoint:
            return False
        
        try:
            url = f"{endpoint.rstrip('/')}/api/v3/channels/join"
            response = requests.post(
                url,
                json={
                    'device_id': self._app.identity.id,
                    'channel_id': channel_id
                },
                timeout=5
            )
            return response.status_code == 200
        except Exception as e:
            log.debug("backend.join_channel_failed", error=str(e))
            return False

    def get_channel_members(self, channel_id: str) -> List[Dict[str, Any]]:
        """Get members of a channel."""
        endpoint = self._app.select_best_server()
        if not endpoint:
            return []
        
        try:
            url = f"{endpoint.rstrip('/')}/api/v3/channels/{channel_id}/members"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return data.get('members', [])
        except Exception as e:
            log.debug("backend.get_channel_members_failed", error=str(e))
        
        return []


class ConnectionAdapter:
    """Adapter for connection methods."""

    def __init__(self, app: NyxApp):
        self._app = app

    def is_connected(self) -> bool:
        """Check if connected to server."""
        if not self._app.connection:
            return False
        if not self._app.connection.session:
            return False
        return self._app.connection.session.is_authenticated()

    def sync_messages(self) -> List[Dict[str, Any]]:
        """Sync messages from server."""
        if not self._app.connection or not self._app.messaging:
            return []
        
        try:
            # Call the connection's sync method
            if hasattr(self._app.connection, 'sync_messages'):
                raw_messages = self._app.connection.sync_messages()
            else:
                # Fallback: return empty list
                raw_messages = []
            
            # Convert to expected format
            result = []
            for msg in raw_messages:
                result.append({
                    'sender_id': msg.get('sender_id', ''),
                    'plaintext': msg.get('plaintext') or msg.get('content', ''),
                    'created_at': msg.get('created_at') or msg.get('timestamp', ''),
                })
            return result
        except Exception as e:
            log.error("connection.sync_messages_failed", error=str(e))
            return []


class StorageAdapter:
    """Adapter for storage methods."""

    def __init__(self, app: NyxApp):
        self._app = app

    @property
    def contacts(self) -> Any:
        """Return contacts store."""
        return ContactsStoreAdapter(self._app)

    @property
    def rooms(self) -> Any:
        """Return rooms store."""
        return self._app.rooms

    @property
    def messages(self) -> Any:
        """Return messages store."""
        return MessagesStoreAdapter(self._app)


class ContactsStoreAdapter:
    """Adapter for contacts store."""

    def __init__(self, app: NyxApp):
        self._app = app

    def get_unread_count(self, device_id: str) -> int:
        """Get unread count for a contact."""
        if not self._app.contacts:
            return 0
        return self._app.contacts.get_unread_count(device_id)

    def add_contact(self, device_id: str, alias: Optional[str] = None) -> None:
        """Add a contact."""
        if not self._app.contacts:
            return
        self._app.contacts.upsert(
            identity_id=device_id,
            display_name=alias,
        )

    def delete(self, device_id: str) -> None:
        """Delete a contact."""
        if not self._app.contacts:
            return
        self._app.contacts.delete(device_id)


class MessagesStoreAdapter:
    """Adapter for messages store."""

    def __init__(self, app: NyxApp):
        self._app = app

    def get_messages(self, device_id: str) -> List[Dict[str, Any]]:
        """Get messages for a contact."""
        if not self._app.messages:
            return []
        
        try:
            messages = self._app.messages.list_by_conversation(device_id)
            result = []
            for msg in messages:
                result.append({
                    'sender_id': msg.sender_id,
                    'plaintext': msg.plaintext,
                    'created_at': msg.created_at,
                })
            return result
        except Exception as e:
            log.error("messages.get_messages_failed", error=str(e))
            return []


class MessagingAdapter:
    """Adapter for messaging methods."""

    def __init__(self, app: NyxApp):
        self._app = app

    def send_direct_message(self, device_id: str, content: str) -> None:
        """Send a direct message."""
        if not self._app.messaging:
            raise RuntimeError("messaging not initialized")
        
        self._app.messaging.send_direct_message(device_id, content)

    def handle_incoming_message(self, msg: Dict[str, Any]) -> None:
        """Handle an incoming message."""
        if not self._app.messaging:
            return
        
        try:
            # Process the message through the messaging service
            if hasattr(self._app.messaging, 'handle_incoming'):
                self._app.messaging.handle_incoming(msg)
        except Exception as e:
            log.error("messaging.handle_incoming_failed", error=str(e))


class ConfigAdapter:
    """Adapter for config access."""

    def __init__(self, app: NyxApp):
        self._app = app

    @property
    def network(self) -> Any:
        """Return network config."""
        return NetworkConfigAdapter(self._app)


class NetworkConfigAdapter:
    """Adapter for network config."""

    def __init__(self, app: NyxApp):
        self._app = app

    @property
    def default_server(self) -> str:
        """Get default server URL."""
        return self._app.settings.network.default_server or ""

    @default_server.setter
    def default_server(self, value: str) -> None:
        """Set default server URL."""
        self._app.settings.network.default_server = value
        # Save settings to disk
        try:
            import tomli_w
            config_path = self._app.settings.config_file
            if config_path:
                # Convert settings to dict
                data = {
                    'network': {
                        'default_server': value,
                    }
                }
                config_path.write_text(tomli_w.dumps(data))
        except Exception as e:
            log.error("config.save_failed", error=str(e))