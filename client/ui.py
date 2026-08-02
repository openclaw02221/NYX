"""
NYX Client UI Module.

Provides both a legacy REPL interface and a modern Textual TUI.
Version: 0.0.5
"""

from __future__ import annotations

import sys
import asyncio
import hashlib
import time
from datetime import datetime
from typing import TextIO, Optional, List, Dict, Any

# Textual imports
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header,
    Footer,
    Static,
    Input,
    ListItem,
    ListView,
    Label,
    Button,
    ContentSwitcher,
    TextArea,
    RichLog,
)
from textual.binding import Binding
from textual.screen import ModalScreen, Screen
from textual.reactive import reactive
from textual.message import Message as TextualMessage

from commands import CommandContext, CommandRegistry, registry as default_registry
from config import get_logger
from db import Message

log = get_logger(__name__)

VERSION = "0.0.5"

BANNER = f"""
┌─────────────────────────────────────────┐
│         NYX Client v{VERSION}               │
│  Secure Terminal-Native Communication   │
│                                         │
│  Type /help for commands, /exit to quit │
└─────────────────────────────────────────┘
"""

# =============================================================================
# MODAL SCREENS
# =============================================================================

class HelpScreen(ModalScreen):
    """Help overlay showing key bindings."""
    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(f"NYX v{VERSION} - Help", id="dialog-title"),
            Static(
                "Ctrl+Q / Ctrl+C : Quit\n"
                "Ctrl+H         : Show this help\n"
                "Ctrl+T         : Cycle themes\n"
                "Ctrl+R         : Force sync\n"
                "Ctrl+N         : Add contact\n"
                "Ctrl+G         : Create group\n"
                "Ctrl+S         : Server settings\n"
                "Ctrl+F         : Search contacts\n"
                "Ctrl+L         : Clear chat display\n"
                "Tab            : Switch focus\n"
                "Esc            : Close / Back",
                id="help-text"
            ),
            Button("Close", variant="primary", id="close-btn"),
            id="dialog-container"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

class ConfirmDialog(ModalScreen[bool]):
    """Generic confirmation dialog."""
    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Confirmation", id="dialog-title"),
            Label(self.message, id="confirm-msg"),
            Horizontal(
                Button("Yes", variant="error", id="yes-btn"),
                Button("No", id="no-btn"),
                classes="dialog-buttons"
            ),
            id="dialog-container"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes-btn")

class AddContactScreen(ModalScreen[Optional[tuple[str, str]]]):
    """Modal for adding a new contact."""
    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Add New Contact", id="dialog-title"),
            Input(placeholder="nyx1... address", id="contact-address"),
            Input(placeholder="Alias (optional)", id="contact-alias"),
            Horizontal(
                Button("Add", variant="primary", id="add-btn"),
                Button("Cancel", id="cancel-btn"),
                classes="dialog-buttons"
            ),
            id="dialog-container"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-btn":
            address = self.query_one("#contact-address", Input).value.strip()
            alias = self.query_one("#contact-alias", Input).value.strip()
            self.dismiss((address, alias) if address else None)
        else:
            self.dismiss(None)

class CreateGroupScreen(ModalScreen[Optional[str]]):
    """Modal for creating a group."""
    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Create New Group", id="dialog-title"),
            Input(placeholder="Group name", id="group-name"),
            Horizontal(
                Button("Create", variant="primary", id="create-btn"),
                Button("Cancel", id="cancel-btn"),
                classes="dialog-buttons"
            ),
            id="dialog-container"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            name = self.query_one("#group-name", Input).value.strip()
            self.dismiss(name if name else None)
        else:
            self.dismiss(None)

class ServerSettingsScreen(ModalScreen[Optional[str]]):
    """Modal for server settings."""
    def __init__(self, current_url: str):
        super().__init__()
        self.current_url = current_url

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Server Settings", id="dialog-title"),
            Input(value=self.current_url, placeholder="Server URL", id="server-url"),
            Horizontal(
                Button("Test", id="test-btn"),
                Button("Save & Reconnect", variant="primary", id="save-btn"),
                Button("Cancel", id="cancel-btn"),
                classes="dialog-buttons"
            ),
            id="dialog-container"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            url = self.query_one("#server-url", Input).value.strip()
            self.dismiss(url if url else None)
        elif event.button.id == "test-btn":
            self.app.notify("Testing connection...", severity="info")
            # Logic for testing would go here
        else:
            self.dismiss(None)

class BrowseChannelsScreen(ModalScreen):
    """Modal for browsing/joining channels."""
    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Browse Channels", id="dialog-title"),
            Input(placeholder="Search channels...", id="search-input"),
            ListView(id="channels-results"),
            Horizontal(
                Button("Join", variant="primary", id="join-btn"),
                Button("Close", id="close-btn"),
                classes="dialog-buttons"
            ),
            id="dialog-container"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

class GroupMembersScreen(ModalScreen):
    """Modal showing group members."""
    def __init__(self, members: list[dict]):
        super().__init__()
        self.members = members

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Group Members", id="dialog-title"),
            ListView(*[ListItem(Label(f"{m.get('alias', 'Unknown')} ({m.get('identity_id', '')[:12]})")) for m in self.members]),
            Button("Close", id="close-btn"),
            id="dialog-container"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

# =============================================================================
# UI COMPONENTS
# =============================================================================

class ChatBubble(Static):
    """A single chat message bubble."""
    def __init__(self, text: str, sender: str, is_own: bool, timestamp: int):
        super().__init__()
        self.text = text
        self.sender = sender
        self.is_own = is_own
        self.time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M")

    def compose(self) -> ComposeResult:
        with Vertical(classes="bubble " + ("own" if self.is_own else "other")):
            if not self.is_own:
                yield Label(self.sender[:16] + "...", classes="sender-name")
            yield Label(self.text, classes="message-text")
            yield Label(self.time_str, classes="timestamp")

# =============================================================================
# MAIN TUI APP
# =============================================================================

class NyxTUI(App):
    """NYX Textual User Interface."""
    
    TITLE = f"NYX v{VERSION}"
    
    CSS = """
    /* Themes */
    .matrix { --primary: #00FF00; --accent: #008800; --panel: #002200; --surface: #001100; --text: #00FF00; }
    .telegram { --primary: #2481CC; --accent: #2481CC; --panel: #FFFFFF; --surface: #F0F0F0; --text: #000000; }
    .monochrome { --primary: #FFFFFF; --accent: #888888; --panel: #111111; --surface: #000000; --text: #FFFFFF; }
    .solarized { --primary: #268BD2; --accent: #2AA198; --panel: #073642; --surface: #002B36; --text: #839496; }

    Screen {
        background: $surface;
        color: $text;
    }

    #sidebar {
        width: 25;
        background: $panel;
        border-right: tall $primary;
    }

    #main-panel {
        width: 1fr;
    }

    .panel-container {
        padding: 1;
        height: 1fr;
    }

    .panel-title {
        text-style: bold;
        background: $primary;
        color: $surface;
        padding: 1;
        margin-bottom: 1;
        width: 100%;
    }

    #chat-view-container {
        height: 1fr;
    }

    #conversation-list {
        width: 30;
        border-right: solid $primary;
    }

    #chat-area {
        height: 1fr;
    }

    #chat-history {
        height: 1fr;
        padding: 1;
        overflow-y: scroll;
    }

    #input-bar {
        height: auto;
        border-top: solid $primary;
        padding: 1;
    }

    #chat-input {
        width: 1fr;
    }

    .bubble {
        margin: 1;
        padding: 1;
        max-width: 70%;
        border-radius: 1;
    }

    .own {
        align-horizontal: right;
        background: $accent;
        color: white;
    }

    .other {
        align-horizontal: left;
        background: $panel;
        border: solid $primary;
    }

    .sender-name {
        text-style: bold;
        font-size: 80%;
        color: $primary;
    }

    .timestamp {
        align-horizontal: right;
        font-size: 70%;
        opacity: 0.7;
    }

    #dialog-container {
        padding: 1 2;
        background: $surface;
        border: thick $primary;
        width: 60;
        height: auto;
        align: center middle;
    }

    #dialog-title {
        text-style: bold;
        margin-bottom: 1;
        text-align: center;
    }

    .dialog-buttons {
        margin-top: 1;
        height: auto;
        align: right middle;
    }

    .dialog-buttons Button {
        margin-left: 1;
    }
    
    #help-text {
        margin: 1 0;
    }

    .unread-badge {
        color: $surface;
        background: $primary;
        padding: 0 1;
        text-style: bold;
    }
    
    .status-header {
        height: 3;
        background: $panel;
        border-bottom: solid $primary;
        padding: 0 1;
        align: center middle;
    }
    
    .status-dot {
        color: #00FF00;
    }
    .status-dot.disconnected {
        color: #FF0000;
    }

    .profile-field {
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit_app", "Quit", show=True),
        Binding("ctrl+h", "help", "Help", show=True),
        Binding("ctrl+t", "cycle_theme", "Theme", show=True),
        Binding("ctrl+r", "force_sync", "Sync", show=True),
        Binding("ctrl+n", "add_contact", "Add Contact", show=True),
        Binding("ctrl+g", "create_group", "New Group", show=True),
        Binding("ctrl+s", "server_settings", "Settings", show=True),
        Binding("ctrl+f", "search_contacts", "Search", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        Binding("delete", "delete_selected", "Delete", show=False),
        Binding("tab", "focus_next", "Focus Next", show=False),
        Binding("escape", "back", "Back", show=False),
    ]

    theme_list = ["matrix", "telegram", "monochrome", "solarized"]
    current_theme_idx = 0

    def __init__(self, ctx: CommandContext):
        super().__init__()
        self.ctx = ctx
        self.active_peer = None
        self.sync_task = None

    def compose(self) -> ComposeResult:
        with Vertical(id="app-container", classes="matrix"):
            # Custom Header
            with Horizontal(classes="status-header"):
                yield Label(f" NYX v{VERSION}  │ ", id="header-version")
                status_text = "● Connected" if (self.ctx and self.ctx.connected) else "○ Disconnected"
                yield Label(status_text, id="header-status")
                yield Label(f"  │  {self.ctx.identity_id[:16]}...  │  ", id="header-id")
                yield Label(self.theme_list[self.current_theme_idx], id="header-theme")

            with Horizontal():
                with Vertical(id="sidebar"):
                    yield ListView(
                        ListItem(Label("💬 CHATS"), id="menu-chats"),
                        ListItem(Label("👥 CONTACTS"), id="menu-contacts"),
                        ListItem(Label("📢 GROUPS"), id="menu-groups"),
                        ListItem(Label("👤 PROFILE"), id="menu-profile"),
                        ListItem(Label("⚙️ SETTINGS"), id="menu-settings"),
                        id="sidebar-menu"
                    )
                
                with ContentSwitcher(initial="chats", id="main-panel"):
                    # CHATS VIEW
                    with Horizontal(id="chats"):
                        yield ListView(id="conversation-list")
                        with Vertical(id="chat-area"):
                            yield ScrollableContainer(id="chat-history")
                            with Horizontal(id="input-bar"):
                                yield Input(placeholder="Type a message...", id="chat-input")
                                yield Button("Send", variant="primary", id="send-btn")
                    
                    # CONTACTS VIEW
                    with Vertical(id="contacts", classes="panel-container"):
                        yield Label("CONTACTS", classes="panel-title")
                        yield ListView(id="contacts-list")
                        with Horizontal(classes="dialog-buttons"):
                            yield Button("[+] Add Contact", variant="primary", id="btn-add-contact")
                            yield Button("[-] Delete Selected", variant="error", id="btn-del-contact")

                    # GROUPS VIEW
                    with Vertical(id="groups", classes="panel-container"):
                        yield Label("GROUPS", classes="panel-title")
                        yield ListView(id="groups-list")
                        with Horizontal(classes="dialog-buttons"):
                            yield Button("[+] Create Group", variant="primary", id="btn-create-group")
                            yield Button("[🔗] Join via ID", id="btn-join-group")
                            yield Button("[-] Leave/Delete", variant="error", id="btn-leave-group")

                    # PROFILE VIEW
                    with Vertical(id="profile", classes="panel-container"):
                        yield Label("PROFILE", classes="panel-title")
                        with ScrollableContainer():
                            yield Label(f"Device ID: {getattr(self.ctx.identity, 'device_id', 'N/A')}", classes="profile-field")
                            yield Label(f"NYX Address: {self.ctx.identity_id}", classes="profile-field")
                            yield Label(f"Public Key: {self.ctx.identity.public_key_bytes.hex()[:32]}...", classes="profile-field")
                            yield Label("Display Name:")
                            yield Input(placeholder="Your Name", id="profile-name")
                            yield Label("Bio:")
                            yield TextArea(id="profile-bio")
                            yield Button("[💾] Save Profile", variant="primary", id="btn-save-profile")

                    # SETTINGS VIEW
                    with Vertical(id="settings", classes="panel-container"):
                        yield Label("SETTINGS", classes="panel-title")
                        yield Label(f"Current Server: {self.ctx.server}")
                        yield Input(placeholder="New Server URL", id="settings-server-url")
                        with Horizontal(classes="dialog-buttons"):
                            yield Button("[🔌] Test Connection", id="btn-test-server")
                            yield Button("[💾] Save & Reconnect", variant="primary", id="btn-save-server")

            yield Footer()

    async def on_mount(self) -> None:
        self.refresh_all()
        # Start background sync
        self.sync_task = asyncio.create_task(self.background_sync())

    async def background_sync(self):
        """Background thread for syncing messages."""
        while True:
            try:
                if self.ctx and self.ctx.connected:
                    # In a real app, call self.ctx.sync()
                    pass
                await asyncio.sleep(5)
            except Exception as e:
                log.error(f"Sync error: {e}")
                await asyncio.sleep(10)

    def refresh_all(self):
        self.refresh_conversations()
        self.refresh_contacts()
        self.refresh_groups()

    def refresh_conversations(self):
        try:
            if not self.ctx or not self.ctx.db: return
            lv = self.query_one("#conversation-list", ListView)
            lv.clear()
            convs = self.ctx.db.list_conversations()
            for c in convs:
                peer = c.get("peer_id", "Unknown")
                item = ListItem(Label(f"💬 {peer[:12]}..."), id=f"conv-{peer}")
                item.peer_id = peer
                lv.append(item)
        except Exception as e:
            self.notify(f"Database error: {e}", severity="error")

    def refresh_contacts(self):
        try:
            if not self.ctx or not self.ctx.db: return
            lv = self.query_one("#contacts-list", ListView)
            lv.clear()
            contacts = self.ctx.db.list_contacts()
            for c in contacts:
                addr = c.get("identity_id", "")
                alias = c.get("display_name") or "No Alias"
                lv.append(ListItem(Label(f"{alias} ({addr[:12]}...)"), id=f"contact-{addr}"))
        except Exception as e:
            self.notify(f"Database error: {e}", severity="error")

    def refresh_groups(self):
        try:
            if not self.ctx or not self.ctx.db: return
            lv = self.query_one("#groups-list", ListView)
            lv.clear()
            # Placeholder for group listing
            # groups = self.ctx.db.list_groups()
        except Exception as e:
            self.notify(f"Database error: {e}", severity="error")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "sidebar-menu":
            menu_map = {
                "menu-chats": "chats",
                "menu-contacts": "contacts",
                "menu-groups": "groups",
                "menu-profile": "profile",
                "menu-settings": "settings"
            }
            target = menu_map.get(event.item.id)
            if target:
                self.query_one("#main-panel", ContentSwitcher).current = target
        
        elif event.list_view.id == "conversation-list":
            peer = getattr(event.item, "peer_id", None)
            if peer:
                self.load_chat(peer)

    def load_chat(self, peer_id: str):
        try:
            self.active_peer = peer_id
            history = self.query_one("#chat-history", ScrollableContainer)
            for child in history.children:
                child.remove()
            
            if not self.ctx.db: return
            
            # Deterministic conversation ID
            sorted_ids = tuple(sorted([self.ctx.identity_id, peer_id]))
            conv_id = hashlib.sha256(f"{sorted_ids[0]}{sorted_ids[1]}".encode()).hexdigest()[:32]
            
            messages = self.ctx.db.get_messages(conv_id, limit=50)
            for msg in messages:
                is_own = msg.sender_id == self.ctx.identity_id
                history.mount(ChatBubble(
                    text=msg.payload.decode("utf-8", errors="replace"),
                    sender=msg.sender_id,
                    is_own=is_own,
                    timestamp=msg.timestamp
                ))
            history.scroll_end(animate=False)
        except Exception as e:
            self.notify(f"Error loading chat: {e}", severity="error")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-input":
            await self.send_msg()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "send-btn":
            await self.send_msg()
        elif btn_id == "btn-add-contact":
            await self.action_add_contact()
        elif btn_id == "btn-del-contact":
            await self.delete_selected_contact()
        elif btn_id == "btn-create-group":
            await self.action_create_group()
        elif btn_id == "btn-save-profile":
            await self.save_profile()
        elif btn_id == "btn-save-server":
            await self.save_server()

    async def send_msg(self):
        if not self.active_peer:
            self.notify("Select a chat first", severity="warning")
            return
        
        inp = self.query_one("#chat-input", Input)
        text = inp.value.strip()
        if not text: return

        try:
            # Backend call integration
            # We simulate saving to DB and updating UI
            peer_id = self.active_peer
            me = self.ctx.identity_id
            sorted_ids = tuple(sorted([me, peer_id]))
            conv_id = hashlib.sha256(f"{sorted_ids[0]}{sorted_ids[1]}".encode()).hexdigest()[:32]
            
            self.ctx.db.ensure_conversation(conv_id, peer_id)
            ts = int(time.time())
            msg_id = hashlib.sha256(f"{me}{peer_id}{ts}".encode()).hexdigest()[:32]
            
            new_msg = Message(
                message_id=msg_id,
                conversation_id=conv_id,
                sender_id=me,
                payload=text.encode("utf-8"),
                sequence=1, # simplified
                timestamp=ts,
                direction="out",
                status="sent"
            )
            self.ctx.db.save_message(new_msg)
            
            history = self.query_one("#chat-history", ScrollableContainer)
            history.mount(ChatBubble(text, me, True, ts))
            history.scroll_end()
            inp.value = ""
            self.refresh_conversations()
        except Exception as e:
            self.notify(f"Failed to send: {e}", severity="error")

    # Action Handlers
    async def action_quit_app(self):
        def check_quit(quit):
            if quit: self.exit()
        self.push_screen(ConfirmDialog("Are you sure you want to quit?"), check_quit)

    async def action_help(self):
        self.push_screen(HelpScreen())

    async def action_cycle_theme(self):
        self.current_theme_idx = (self.current_theme_idx + 1) % len(self.theme_list)
        new_theme = self.theme_list[self.current_theme_idx]
        container = self.query_one("#app-container")
        for t in self.theme_list:
            container.remove_class(t)
        container.add_class(new_theme)
        self.query_one("#header-theme", Label).update(new_theme)

    async def action_force_sync(self):
        self.notify("Syncing with server...")
        # try: self.ctx.sync()
        self.refresh_all()

    async def action_add_contact(self):
        def handle_add(res):
            if res:
                addr, alias = res
                try:
                    self.ctx.db.save_contact(addr, alias)
                    self.notify(f"Added {alias or addr[:12]}")
                    self.refresh_contacts()
                except Exception as e:
                    self.notify(str(e), severity="error")
        self.push_screen(AddContactScreen(), handle_add)

    async def action_create_group(self):
        def handle_create(name):
            if name:
                self.notify(f"Group '{name}' created (simulated)")
        self.push_screen(CreateGroupScreen(), handle_create)

    async def action_server_settings(self):
        def handle_server(url):
            if url:
                self.ctx.server = url
                self.notify(f"Server set to {url}")
        self.push_screen(ServerSettingsScreen(self.ctx.server or ""), handle_server)

    async def action_search_contacts(self):
        self.notify("Search not implemented yet")

    async def action_clear_chat(self):
        history = self.query_one("#chat-history", ScrollableContainer)
        for child in history.children:
            child.remove()

    async def delete_selected_contact(self):
        # Implementation depends on selection
        self.notify("Select a contact to delete")

    async def save_profile(self):
        name = self.query_one("#profile-name", Input).value
        bio = self.query_one("#profile-bio", TextArea).text
        try:
            if hasattr(self.ctx, 'update_profile'):
                self.ctx.update_profile(name, bio)
            else:
                self.notify("Feature coming soon", severity="info")
        except Exception as e:
            self.notify(str(e), severity="error")

    async def save_server(self):
        url = self.query_one("#settings-server-url", Input).value
        if url:
            self.ctx.server = url
            self.notify("Server updated")

# =============================================================================
# Legacy REPL UI Wrapper
# =============================================================================

class ReplUI:
    """Simple line-oriented terminal interface."""

    def __init__(
        self,
        ctx: CommandContext,
        commands: Optional[CommandRegistry] = None,
        stdin: Optional[TextIO] = None,
        stdout: Optional[TextIO] = None,
    ) -> None:
        self.ctx = ctx
        self.commands = commands or default_registry
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout

    def print(self, text: str) -> None:
        """Print text to stdout."""
        self.stdout.write(text + "\n")
        self.stdout.flush()

    def run_line(self, line: str) -> bool:
        """Process one input line."""
        result = self.commands.dispatch(self.ctx, line)
        if result.message == "__EXIT__":
            self.print("Goodbye.")
            return False
        if result.message:
            prefix = "" if result.ok else "error: "
            self.print(prefix + result.message)
        return True

    def run(self) -> int:
        """Entry point for UI. Detects whether to run TUI or REPL."""
        if "--repl" in sys.argv:
            return self._run_repl()
        else:
            app = NyxTUI(self.ctx)
            app.run()
            return 0

    def _run_repl(self) -> int:
        """Interactive REPL loop."""
        self.print(BANNER)
        if self.ctx.identity_id:
            self.print(f"  Identity: {self.ctx.identity_id}")
        self.print("")
        
        while True:
            try:
                self.stdout.write("nyx> ")
                self.stdout.flush()
                line = self.stdin.readline()
                if line == "":
                    self.print("")
                    break
                if not self.run_line(line):
                    break
            except KeyboardInterrupt:
                self.print("\n(interrupted — type /exit to quit)")
            except EOFError:
                self.print("")
                break
        return 0

# =============================================================================
# Helper display functions
# =============================================================================

def display_welcome(identity_id: str, mnemonic: Optional[str] = None) -> None:
    """Display welcome message for new or existing identity."""
    if mnemonic:
        print("\n" + "=" * 60)
        print("  *** NEW IDENTITY CREATED ***")
        print(f"  {identity_id}")
        print()
        print("  Recovery mnemonic (store offline, never share):")
        print(f"  {mnemonic}")
        print("=" * 60 + "\n")
    else:
        print(f"\nLoaded identity: {identity_id}\n")

def display_error(message: str) -> None:
    """Display error message."""
    print(f"Error: {message}", file=sys.stderr)

def display_status(connected: bool, server: str, identity: str) -> None:
    """Display current status."""
    status = "connected" if connected else "disconnected"
    print(f"\nStatus: {status}")
    print(f"Server: {server}")
    print(f"Identity: {identity[:32]}...\n")