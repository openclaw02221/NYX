from datetime import datetime
from typing import List, Optional, Dict, Any
import asyncio

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, Input, ListView, ListItem, Label, Button
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from textual import on, work
from textual.events import Mount

from nyx_client.config.defaults import VERSION
from nyx_client.protocol.types import ConversationType, MessageDirection, MessageStatus

class HeaderBar(Static):
    """Custom header for NYX."""
    
    status = reactive("Disconnected")
    identity = reactive("Unknown")
    theme_name = reactive("default")

    def render(self) -> str:
        return f" NYX v{VERSION} │ {self.status} │ {self.identity} │ Theme: {self.theme_name} "

class ContactItem(ListItem):
    """An item in the contact list (contact or group)."""
    
    def __init__(self, contact: Dict[str, Any], unread_count: int = 0, is_group: bool = False):
        super().__init__()
        self.contact = contact
        self.is_group = is_group
        if is_group:
            self.device_id = contact.get('room_id', '')
            self.alias = contact.get('title', 'Unnamed Group')
        else:
            self.device_id = contact['device_id']
            self.alias = contact.get('alias') or self.device_id[:12]
        self.unread_count = unread_count

    def compose(self) -> ComposeResult:
        unread_badge = f" [{self.unread_count}]" if self.unread_count > 0 else ""
        prefix = "◆" if self.is_group else "●"
        yield Label(f"{prefix} {self.alias}{unread_badge}")

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

class HelpScreen(ModalScreen[None]):
    """Help overlay showing all key bindings."""
    
    BINDINGS = [("escape", "dismiss", "Close")]
    
    def compose(self) -> ComposeResult:
        help_text = """
╔═══════════════════════════════════════════════════════════╗
║           NYX v0.0.5 - KEY BINDINGS REFERENCE            ║
╠═══════════════════════════════════════════════════════════╣
║ GLOBAL BINDINGS:                                         ║
║   Ctrl+Q     - Quit application (with confirmation)      ║
║   Ctrl+H     - Show this help                            ║
║   Ctrl+T     - Cycle theme                               ║
║   Ctrl+R     - Force sync messages                       ║
║   Ctrl+N     - Add new contact                           ║
║   Ctrl+G     - Create new group                          ║
║   Ctrl+S     - Server settings                           ║
║   Ctrl+L     - Clear chat display                        ║
║                                                           ║
║ CONTACT LIST:                                            ║
║   Up/Down    - Navigate contacts                         ║
║   Enter      - Open chat with contact                    ║
║   Delete     - Delete selected contact                   ║
║                                                           ║
║ NAVIGATION:                                              ║
║   Tab        - Focus next widget                         ║
║   Shift+Tab  - Focus previous widget                     ║
║   Escape     - Go back/Cancel                            ║
╚═══════════════════════════════════════════════════════════╝
        """
        with Container(id="help_modal"):
            yield Static(help_text, id="help_content")
            yield Button("Close [Esc]", id="help_close_btn")
    
    @on(Button.Pressed, "#help_close_btn")
    def close_help(self):
        self.dismiss()

class ServerSettingsScreen(ModalScreen[Optional[str]]):
    """Server settings dialog."""
    
    BINDINGS = [("escape", "dismiss", "Cancel")]
    
    def __init__(self, current_url: str):
        super().__init__()
        self.current_url = current_url
    
    def compose(self) -> ComposeResult:
        with Container(id="server_modal"):
            yield Static("╔═══════════ SERVER SETTINGS ════════════╗", id="server_title")
            yield Label(f"Current: {self.current_url}")
            yield Input(placeholder="Enter new server URL", id="server_url_input")
            yield Static("", id="test_result")
            with Horizontal(id="server_buttons"):
                yield Button("Test Connection", id="test_btn", variant="primary")
                yield Button("Save & Reconnect", id="save_btn", variant="success")
                yield Button("Cancel [Esc]", id="cancel_btn")
    
    @on(Button.Pressed, "#test_btn")
    async def test_connection(self):
        input_widget = self.query_one("#server_url_input", Input)
        url = input_widget.value.strip()
        if not url:
            self.query_one("#test_result", Static).update("⚠ Please enter a URL")
            return
        
        result_widget = self.query_one("#test_result", Static)
        result_widget.update("⏳ Testing connection...")
        
        try:
            import requests
            response = requests.get(f"{url}/api/v3/health", timeout=5)
            if response.status_code == 200:
                result_widget.update("✓ Connected successfully")
            else:
                result_widget.update(f"✗ Failed: HTTP {response.status_code}")
        except Exception as e:
            result_widget.update(f"✗ Failed: {str(e)[:50]}")
    
    @on(Button.Pressed, "#save_btn")
    def save_settings(self):
        input_widget = self.query_one("#server_url_input", Input)
        url = input_widget.value.strip()
        if url:
            self.dismiss(url)
        else:
            self.query_one("#test_result", Static).update("⚠ Please enter a URL")
    
    @on(Button.Pressed, "#cancel_btn")
    def cancel(self):
        self.dismiss(None)

class AddContactScreen(ModalScreen[Optional[Dict[str, str]]]):
    """Add contact dialog."""
    
    BINDINGS = [("escape", "dismiss", "Cancel")]
    
    def compose(self) -> ComposeResult:
        with Container(id="add_contact_modal"):
            yield Static("╔═══════════ ADD NEW CONTACT ════════════╗", id="add_contact_title")
            yield Input(placeholder="Paste nyx1... address", id="contact_address_input")
            yield Input(placeholder="Alias (optional)", id="contact_alias_input")
            with Horizontal(id="add_contact_buttons"):
                yield Button("Add Contact", id="add_btn", variant="success")
                yield Button("Cancel [Esc]", id="cancel_btn")
    
    @on(Button.Pressed, "#add_btn")
    def add_contact(self):
        address = self.query_one("#contact_address_input", Input).value.strip()
        alias = self.query_one("#contact_alias_input", Input).value.strip()
        if address:
            self.dismiss({"address": address, "alias": alias})
        else:
            self.notify("Please enter a nyx address", severity="warning")
    
    @on(Button.Pressed, "#cancel_btn")
    def cancel(self):
        self.dismiss(None)

class CreateGroupScreen(ModalScreen[Optional[str]]):
    """Create group dialog."""
    
    BINDINGS = [("escape", "dismiss", "Cancel")]
    
    def compose(self) -> ComposeResult:
        with Container(id="create_group_modal"):
            yield Static("╔═══════════ CREATE NEW GROUP ════════════╗", id="create_group_title")
            yield Input(placeholder="Group name", id="group_name_input")
            yield Input(placeholder="Description (optional)", id="group_desc_input")
            with Horizontal(id="create_group_buttons"):
                yield Button("Create Group", id="create_btn", variant="success")
                yield Button("Cancel [Esc]", id="cancel_btn")
    
    @on(Button.Pressed, "#create_btn")
    def create_group(self):
        name = self.query_one("#group_name_input", Input).value.strip()
        if name:
            self.dismiss(name)
        else:
            self.notify("Please enter a group name", severity="warning")
    
    @on(Button.Pressed, "#cancel_btn")
    def cancel(self):
        self.dismiss(None)

class ConfirmDialog(ModalScreen[bool]):
    """Generic confirmation dialog."""
    
    BINDINGS = [("escape", "cancel", "Cancel")]
    
    def __init__(self, message: str, title: str = "Confirm"):
        super().__init__()
        self.message = message
        self.title = title
    
    def compose(self) -> ComposeResult:
        with Container(id="confirm_modal"):
            yield Static(f"╔═══════════ {self.title.upper()} ════════════╗", id="confirm_title")
            yield Label(self.message)
            with Horizontal(id="confirm_buttons"):
                yield Button("Yes", id="yes_btn", variant="error")
                yield Button("No [Esc]", id="no_btn", variant="primary")
    
    @on(Button.Pressed, "#yes_btn")
    def confirm_yes(self):
        self.dismiss(True)
    
    @on(Button.Pressed, "#no_btn")
    def confirm_no(self):
        self.dismiss(False)
    
    def action_cancel(self):
        self.dismiss(False)

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

    #chat_header {
        height: 1;
        background: $panel;
        padding: 0 1;
        border-bottom: solid $primary;
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
    
    #help_modal, #server_modal, #add_contact_modal, #create_group_modal, #confirm_modal {
        width: 70;
        height: auto;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }
    
    #help_content {
        margin: 1 0;
        color: $text;
    }
    
    #server_buttons, #add_contact_buttons, #create_group_buttons, #confirm_buttons {
        width: 100%;
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    
    Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit_confirm", "Quit", show=True),
        Binding("ctrl+h", "show_help", "Help", show=True),
        Binding("ctrl+t", "cycle_theme", "Theme", show=True),
        Binding("ctrl+n", "new_contact", "New", show=True),
        Binding("ctrl+g", "new_group", "Group", show=True),
        Binding("ctrl+s", "server_settings", "Server", show=True),
        Binding("ctrl+r", "sync", "Sync", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        Binding("delete", "delete_contact", "Delete", show=False),
        Binding("tab", "focus_next", "Next", show=False),
    ]

    active_contact = reactive(None)

    def __init__(self, nyx_app=None):
        super().__init__()
        self.nyx_app = nyx_app
        self.header_bar = HeaderBar()
        self.theme_cycle = ["midnight", "ember", "forest", "violet", "mono", "ocean"]
        self.current_theme_index = 0

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield self.header_bar
        with Horizontal(id="main_container"):
            with Vertical(id="sidebar"):
                yield Label(" CONTACTS ", id="sidebar_title")
                yield ListView(id="contact_list")
            with Vertical(id="chat_area"):
                yield Static("", id="chat_header")
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
        """Refresh the contact list from the application state (contacts + groups)."""
        if not self.nyx_app:
            return
        
        self.nyx_app.load_contacts()
        contact_list = self.query_one("#contact_list", ListView)
        contact_list.clear()
        
        # Add contacts
        for contact in self.nyx_app.contacts:
            unread = self.nyx_app.storage.contacts.get_unread_count(contact['device_id'])
            contact_list.append(ContactItem(contact, unread, is_group=False))
        
        # Add groups/rooms
        try:
            rooms = self.nyx_app.storage.rooms.list_all()
            for room in rooms:
                room_dict = {
                    'room_id': room.room_id,
                    'title': room.title,
                    'room_type': room.room_type,
                    'owner_id': room.owner_id
                }
                contact_list.append(ContactItem(room_dict, 0, is_group=True))
        except Exception:
            pass  # Groups not yet supported or database issue

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
        """Refresh the chat window with messages from the active contact or group."""
        if not self.active_contact or not self.nyx_app:
            return
        
        # Determine if this is a group or DM
        is_group = 'room_id' in self.active_contact
        
        # Update chat header
        chat_header = self.query_one("#chat_header", Static)
        if is_group:
            room_id = self.active_contact['room_id']
            title = self.active_contact.get('title', 'Unnamed Group')
            room_type = self.active_contact.get('room_type', 'private_group')
            chat_header.update(f"Group: {title} ({room_type})")
        else:
            alias = self.active_contact.get('alias') or self.active_contact['device_id'][:12]
            addr = self.active_contact.get('device_id', '')[:20]
            chat_header.update(f"Chat: {alias} ({addr}...)")
        
        chat_messages = self.query_one("#chat_messages", Vertical)
        # Clear existing messages
        for child in chat_messages.children:
            child.remove()
        
        # Load messages from storage
        if is_group:
            # Group messages: load from conversation with room_id
            # For MVP, groups may not have message history yet
            chat_messages.mount(Static("Group chat (messaging coming soon)"))
        else:
            device_id = self.active_contact['device_id']
            messages = self.nyx_app.storage.messages.get_messages(device_id)
            
            for msg in messages:
                is_self = msg['sender_id'] == self.nyx_app.identity.device_id
                sender_name = self.active_contact.get('alias') if not is_self else "You"
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

    def action_show_help(self) -> None:
        """Show help overlay with key bindings."""
        self.push_screen(HelpScreen())
    
    def action_cycle_theme(self) -> None:
        """Cycle through available themes."""
        self.current_theme_index = (self.current_theme_index + 1) % len(self.theme_cycle)
        theme_name = self.theme_cycle[self.current_theme_index]
        self.header_bar.theme_name = theme_name
        self.notify(f"Theme: {theme_name}")
    
    async def action_new_contact(self) -> None:
        """Open dialog to add a new contact."""
        result = await self.push_screen_wait(AddContactScreen())
        if result and self.nyx_app:
            try:
                # Add contact to database
                self.nyx_app.storage.contacts.add_contact(
                    device_id=result["address"],
                    alias=result["alias"] or None
                )
                self.refresh_contacts()
                self.notify(f"✓ Added contact: {result['alias'] or result['address'][:12]}")
            except Exception as e:
                self.notify(f"Failed to add contact: {e}", severity="error")

    async def action_server_settings(self) -> None:
        """Open server settings dialog."""
        if not self.nyx_app:
            return
        
        current_url = getattr(self.nyx_app.config.network, 'default_server', 'Unknown')
        result = await self.push_screen_wait(ServerSettingsScreen(current_url))
        
        if result:
            # Update config and reconnect
            self.nyx_app.config.network.default_server = result
            # TODO: Save to config.toml and reconnect
            self.header_bar.status = f"Server: {result}"
            self.notify(f"✓ Server updated: {result}")
    
    async def action_new_group(self) -> None:
        """Open dialog to create a new group."""
        if not self.nyx_app:
            return
        
        result = await self.push_screen_wait(CreateGroupScreen())
        if result:
            try:
                # Create group in database
                room = self.nyx_app.storage.rooms.create(
                    room_type="private_group",
                    title=result,
                    owner_id=self.nyx_app.identity.device_id
                )
                self.refresh_contacts()
                self.notify(f"✓ Created group: {result}")
            except Exception as e:
                self.notify(f"Failed to create group: {e}", severity="error")
    
    def action_clear_chat(self) -> None:
        """Clear the chat display (not history)."""
        chat_messages = self.query_one("#chat_messages", Vertical)
        for child in chat_messages.children:
            child.remove()
        self.notify("Chat display cleared")
    
    async def action_delete_contact(self) -> None:
        """Delete the currently selected contact."""
        if not self.active_contact or not self.nyx_app:
            return
        
        alias = self.active_contact.get('alias') or self.active_contact['device_id'][:12]
        confirm = await self.push_screen_wait(
            ConfirmDialog(
                f"Delete contact '{alias}'?\nThis will remove all message history.",
                title="Delete Contact"
            )
        )
        
        if confirm:
            try:
                device_id = self.active_contact['device_id']
                # Delete from database
                self.nyx_app.storage.contacts.delete(device_id)
                self.active_contact = None
                self.action_clear_chat()
                self.refresh_contacts()
                self.notify(f"✓ Deleted contact: {alias}")
            except Exception as e:
                self.notify(f"Failed to delete contact: {e}", severity="error")
    
    async def action_quit_confirm(self) -> None:
        """Confirm before quitting."""
        confirm = await self.push_screen_wait(
            ConfirmDialog("Are you sure you want to quit NYX?", title="Quit")
        )
        if confirm:
            self.exit()

if __name__ == "__main__":
    app = NYXApp()
    app.run()
