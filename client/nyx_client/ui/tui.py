from datetime import datetime
from typing import List, Optional, Dict, Any
import asyncio

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Input, ListView, ListItem, Label
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen
from textual import on, work
from textual.events import Mount

from nyx_client.config.defaults import VERSION
from nyx_client.protocol.types import MessageType

class HeaderBar(Static):
    """Custom header for NYX."""
    
    status = reactive("Disconnected")
    identity = reactive("Unknown")
    theme_name = reactive("default")

    def render(self) -> str:
        return f" NYX v{VERSION} │ {self.status} │ {self.identity} │ Theme: {self.theme_name} "

class ContactItem(ListItem):
    """An item in the contact list."""
    
    def __init__(self, contact: Dict[str, Any], unread_count: int = 0):
        super().__init__()
        self.contact = contact
        self.device_id = contact['device_id']
        self.alias = contact.get('alias') or self.device_id[:12]
        self.unread_count = unread_count

    def compose(self) -> ComposeResult:
        unread_badge = f" [{self.unread_count}]" if self.unread_count > 0 else ""
        yield Label(f"● {self.alias}{unread_badge}")

class ChatMessage(Static):
    """A message in the chat window."""
    
    def __init__(self, sender: str, content: str, timestamp: datetime, is_self: bool = False):
        super().__init__()
        self.sender = sender
        self.content = content
        self.timestamp = timestamp
        self.is_self = is_self

    def render(self) -> str:
        time_str = self.timestamp.strftime("%H:%M")
        sender_name = "You" if self.is_self else self.sender
        return f"[{time_str}] {sender_name}: {self.content}"

class NYXApp(App):
    """Main Textual application for NYX."""

    TITLE = f"NYX v{VERSION}"
    CSS = """
    Screen {
        background: $surface;
    }

    #main_container {
        layout: horizontal;
    }

    #sidebar {
        width: 30;
        background: $panel;
        border-right: tall $primary;
    }

    #chat_area {
        width: 1fr;
        layout: vertical;
    }

    #chat_messages {
        height: 1fr;
        overflow-y: scroll;
        padding: 1;
        border-bottom: solid $primary;
    }

    #input_bar {
        height: 3;
        margin: 0 1;
    }

    HeaderBar {
        background: $primary;
        color: $on-primary;
        height: 1;
        content-align: center middle;
    }

    ContactItem {
        padding: 0 1;
    }

    ChatMessage {
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+n", "new_contact", "New", show=True),
        Binding("ctrl+s", "server_settings", "Server", show=True),
        Binding("ctrl+r", "sync", "Sync", show=True),
        Binding("tab", "focus_next", "Next", show=False),
    ]

    active_contact = reactive(None)

    def __init__(self, nyx_app=None):
        super().__init__()
        self.nyx_app = nyx_app
        self.header_bar = HeaderBar()

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield self.header_bar
        with Horizontal(id="main_container"):
            with Vertical(id="sidebar"):
                yield Label(" CONTACTS ", id="sidebar_title")
                yield ListView(id="contact_list")
            with Vertical(id="chat_area"):
                yield Vertical(id="chat_messages")
                yield Input(placeholder="Type a message...", id="input_bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Called when the app is mounted."""
        if self.nyx_app:
            self.header_bar.identity = self.nyx_app.identity.address if self.nyx_app.identity else "Unknown"
            self.header_bar.status = "Connected" if self.nyx_app.connection.is_connected() else "Disconnected"
            self.refresh_contacts()
            self.run_background_sync()

    def refresh_contacts(self) -> None:
        """Refresh the contact list from the application state."""
        if not self.nyx_app:
            return
        
        self.nyx_app.load_contacts()
        contact_list = self.query_one("#contact_list", ListView)
        contact_list.clear()
        
        for contact in self.nyx_app.contacts:
            unread = self.nyx_app.storage.contacts.get_unread_count(contact['device_id'])
            contact_list.append(ContactItem(contact, unread))

    @work(exclusive=True)
    async def run_background_sync(self) -> None:
        """Background task to sync messages."""
        while True:
            if self.nyx_app and self.nyx_app.connection.is_connected():
                try:
                    # Sync logic
                    messages = self.nyx_app.connection.sync_messages()
                    if messages:
                        for msg in messages:
                            self.nyx_app.messaging.handle_incoming_message(msg)
                        self.refresh_contacts()
                        # If active contact matches sender, refresh chat
                        if self.active_contact:
                            self.refresh_chat()
                except Exception:
                    pass
            await asyncio.sleep(5)

    @on(ListView.Selected)
    def on_contact_selected(self, event: ListView.Selected) -> None:
        """Handle contact selection."""
        if isinstance(event.item, ContactItem):
            self.active_contact = event.item.contact
            self.refresh_chat()

    def refresh_chat(self) -> None:
        """Refresh the chat window with messages from the active contact."""
        if not self.active_contact or not self.nyx_app:
            return
        
        chat_messages = self.query_one("#chat_messages", Vertical)
        # Clear existing messages
        for child in chat_messages.children:
            child.remove()
        
        # Load messages from storage
        device_id = self.active_contact['device_id']
        messages = self.nyx_app.storage.messages.get_messages(device_id)
        
        for msg in messages:
            is_self = msg['sender_id'] == self.nyx_app.identity.device_id
            sender_name = self.active_contact['alias'] if not is_self else "You"
            ts = datetime.fromisoformat(msg['timestamp']) if isinstance(msg['timestamp'], str) else msg['timestamp']
            chat_messages.mount(ChatMessage(sender_name, msg['content'], ts, is_self))
        
        # Scroll to bottom
        chat_messages.scroll_end(animate=False)

    @on(Input.Submitted, "#input_bar")
    async def on_message_submitted(self, event: Input.Submitted) -> None:
        """Handle message submission."""
        content = event.value.strip()
        if not content or not self.active_contact or not self.nyx_app:
            return
        
        device_id = self.active_contact['device_id']
        try:
            # Send message
            self.nyx_app.messaging.send_direct_message(device_id, content)
            # Clear input
            self.query_one("#input_bar", Input).value = ""
            # Refresh chat
            self.refresh_chat()
        except Exception as e:
            self.notify(f"Failed to send message: {e}", severity="error")

    def action_sync(self) -> None:
        """Force a sync."""
        if self.nyx_app:
            self.nyx_app.sync()
            self.refresh_contacts()
            self.refresh_chat()
            self.notify("Synced with server")

    def action_new_contact(self) -> None:
        """Open a dialog to add a new contact."""
        # For now, just a notification as I haven't implemented the dialog yet
        self.notify("Ctrl+N: Add contact not implemented yet in this view")

    def action_server_settings(self) -> None:
        """Open server settings."""
        self.notify("Ctrl+S: Server settings not implemented yet in this view")

if __name__ == "__main__":
    app = NYXApp()
    app.run()