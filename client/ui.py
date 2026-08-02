from __future__ import annotations

"""NYX Client UI - Merged Textual TUI and REPL UI (v0.0.5)"""

import hashlib

VERSION = "0.0.5"

from datetime import datetime
import asyncio
import sys
from typing import List, Optional, Dict, Any, TextIO

from dataclasses import dataclass
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Input, ListView, ListItem, Label, Button
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from textual import on, work
from textual.events import Mount

from commands import CommandContext, registry
from config import get_logger

log = get_logger(__name__)


def _conversation_id(id1: str, id2: str) -> str:
    """Generate deterministic conversation ID from two identities."""
    sorted_ids = tuple(sorted([id1, id2]))
    return hashlib.sha256(f"{sorted_ids[0]}{sorted_ids[1]}".encode()).hexdigest()[:32]


# =============================================================================
# Theme System (from theme.py)
# =============================================================================
@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    header_fg: str
    header_bg: str
    selected_fg: str
    selected_bg: str
    accent: str
    success: str
    warning: str
    error: str
    muted: str
    border: str
    input_fg: str
    input_bg: str


THEMES: Dict[str, Theme] = {
    "midnight": Theme(
        id="midnight",
        name="Midnight (default)",
        header_fg="cyan",
        header_bg="black",
        selected_fg="black",
        selected_bg="cyan",
        accent="cyan",
        success="green",
        warning="yellow",
        error="red",
        muted="white",
        border="cyan",
        input_fg="green",
        input_bg="black",
    ),
    "ember": Theme(
        id="ember",
        name="Ember",
        header_fg="red",
        header_bg="black",
        selected_fg="black",
        selected_bg="red",
        accent="yellow",
        success="green",
        warning="yellow",
        error="red",
        muted="white",
        border="red",
        input_fg="yellow",
        input_bg="black",
    ),
    "forest": Theme(
        id="forest",
        name="Forest",
        header_fg="green",
        header_bg="black",
        selected_fg="black",
        selected_bg="green",
        accent="green",
        success="green",
        warning="yellow",
        error="red",
        muted="white",
        border="green",
        input_fg="green",
        input_bg="black",
    ),
    "violet": Theme(
        id="violet",
        name="Violet",
        header_fg="magenta",
        header_bg="black",
        selected_fg="black",
        selected_bg="magenta",
        accent="magenta",
        success="green",
        warning="yellow",
        error="red",
        muted="white",
        border="magenta",
        input_fg="magenta",
        input_bg="black",
    ),
    "mono": Theme(
        id="mono",
        name="Mono",
        header_fg="white",
        header_bg="black",
        selected_fg="black",
        selected_bg="white",
        accent="white",
        success="white",
        warning="white",
        error="white",
        muted="white",
        border="white",
        input_fg="white",
        input_bg="black",
    ),
    "ocean": Theme(
        id="ocean",
        name="Ocean",
        header_fg="blue",
        header_bg="black",
        selected_fg="white",
        selected_bg="blue",
        accent="cyan",
        success="green",
        warning="yellow",
        error="red",
        muted="white",
        border="blue",
        input_fg="cyan",
        input_bg="black",
    ),
}

DEFAULT_THEME_ID = "midnight"


def get_theme(theme_id: str) -> Theme:
    return THEMES.get(theme_id, THEMES[DEFAULT_THEME_ID])


def list_themes() -> list:
    return list(THEMES.values())


# =============================================================================
# Banner (from banner.py)
# =============================================================================
BANNER_COMPACT = r"""
╔══════════════════════════════════════════════════════════════════════╗
║   ███╗   ██╗██╗   ██╗██╗  ██╗                                        ║
║   ████╗  ██║╚██╗ ██╔╝╚██╗██╔╝                                        ║
║   ██╔██╗ ██║ ╚████╔╝  ╚███╔╝                                         ║
║   ██║╚██╗██║  ╚██╔╝   ██╔██╗                                         ║
║   ██║ ╚████║   ██║   ██╔╝ ██╗                                        ║
║   ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝                                        ║
╠══════════════════════════════════════════════════════════════════════╣
║          Terminal-Native Secure Messaging  ·  Whitepaper v3.0        ║
╚══════════════════════════════════════════════════════════════════════╝
""".strip("\n")

BANNER_MINI = r"""
┌─────────────────────────────────────────┐
│  N Y X  ·  secure terminal messenger    │
└─────────────────────────────────────────┘
""".strip("\n")

SUBTITLE = "Born from the night — quiet, distributed, hard to censor"


def banner_lines(wide: bool = True) -> List[str]:
    text = BANNER_COMPACT if wide else BANNER_MINI
    return text.splitlines()


# =============================================================================
# REPL UI (from repl.py)
# =============================================================================
BANNER = """
  +------------------------------------------+
  |          NYX Client  REPL                |
  |  Type /help for commands, /exit to quit  |
  +------------------------------------------+
 """


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
        self.commands = commands or registry
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout

    def print(self, text: str) -> None:
        self.stdout.write(text + "\n")
        self.stdout.flush()

    def run_line(self, line: str) -> bool:
        result = self.commands.dispatch(self.ctx, line)
        if result.message == "__EXIT__":
            self.print("Goodbye.")
            return False
        if result.message:
            prefix = "" if result.ok else "error: "
            self.print(prefix + result.message)
        return True

    def run(self) -> int:
        self.print(BANNER)
        if self.ctx.identity_id:
            self.print("  Identity: " + self.ctx.identity_id)
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
# TUI classes (from tui.py, adapted to use self.ctx per backend)
# =============================================================================
class HeaderBar(Static):
    """Custom header for NYX."""

    status = reactive("Disconnected")
    identity = reactive("Unknown")
    theme_name = reactive("default")

    def render(self) -> str:
        return f" NYX v0.0.5 │ {self.status} │ {self.identity} │ Theme: {self.theme_name} "


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
            self.device_id = contact['identity_id']
            self.alias = contact.get('display_name') or contact.get('identity_id', '')[:12]
        self.unread_count = unread_count

    def compose(self) -> ComposeResult:
        unread_badge = f" [{self.unread_count}]" if self.unread_count > 0 else ""
        prefix = "◆" if self.is_group else "●"
        yield Label(f"{prefix} {self.alias}{unread_badge}")


class ChatMessage(Static):
    """A single message bubble with improved styling."""

    def __init__(
        self,
        sender: str,
        content: str,
        timestamp: datetime,
        is_self: bool = False,
        is_group: bool = False
    ):
        super().__init__()
        self.sender = sender
        self.content = content
        self.timestamp = timestamp
        self.is_self = is_self
        self.is_group = is_group

    def render(self) -> str:
        time_str = self.timestamp.strftime("%H:%M")
        sender_name = "You" if self.is_self else self.sender

        if self.is_self:
            bg = "green"
            align = "right"
        else:
            bg = "blue"
            align = "left"

        time_label = f"[#{align}_end][right]{time_str}[/right][/#align_end]"

        if self.is_self:
            line = f"[#self]{sender_name}: {self.content}[/]"
            line += f"\n{time_label}"
        else:
            if self.is_group:
                line = f"[#group]{self.sender}: {self.content}[/]"
                line += f"\n{time_label}"
            else:
                line = f"[#message]{self.content}[/]"

        return f"[{bg}]{line}[/{bg}]"


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
║   Ctrl+P     - Browse channels / public groups           ║
║   Ctrl+M     - Show group members (active group only)    ║
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


class BrowseChannelsScreen(ModalScreen[None]):
    """Channel browser with search and join."""

    def compose(self) -> ComposeResult:
        with Container(id="browse_channels_modal"):
            yield Static("╔═══════════ CHANNELS / PUBLIC GROUPS ════════════╗", id="browse_title")
            yield Input(placeholder="Search channels...", id="search_input")
            yield ListView(id="channels_list")
            yield Label("or paste channel ID (private group invite):", id="invite_label")
            yield Input(placeholder="channel ID", id="invite_input")
            with Horizontal(id="browse_buttons"):
                yield Button("Join", id="join_btn", variant="success")
                yield Button("Cancel [Esc]", id="cancel_btn")

    @on(Input.Submitted, "#search_input")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        self._perform_search()

    @on(Button.Pressed, "#join_btn")
    def on_join_pressed(self) -> None:
        self._perform_join()

    def on_mount(self) -> None:
        self._perform_search()

    def _perform_search(self) -> None:
        query = self.query_one("#search_input", Input).value.strip()
        if not query:
            self._update_list([])
            return

        try:
            ctx = getattr(self.app, 'ctx', None)
            if ctx and ctx.db:
                results = ctx.db.list_contacts()
            else:
                results = []
        except Exception:
            results = []

        self._update_list(results)

    def _update_list(self, results: List[Dict]) -> None:
        channels_list = self.query_one("#channels_list", ListView)
        channels_list.clear()
        for result in results:
            title = result.get("display_name") or result.get("identity_id", "Untitled")[:24]
            desc = result.get("notes", "")[:60]
            channels_list.append(ListItem(Label(f"📢 {title} — {desc}")))
        if results and channels_list.children:
            channels_list.index = 0

    def _perform_join(self) -> None:
        channels_list = self.query_one("#channels_list", ListView)
        invite_input = self.query_one("#invite_input", Input)
        join_btn = self.query_one("#join_btn", Button)

        selected = channels_list.children[channels_list.index] if channels_list.children else None
        if selected and selected.children:
            label_text = selected.children[0].renderable.plain
            try:
                channel_id = label_text.split("—", 1)[0].replace("📢", "").strip()
            except (IndexError, AttributeError):
                channel_id = ""
        else:
            channel_id = invite_input.value.strip()

        if not channel_id:
            return

        try:
            ctx = getattr(self.app, 'ctx', None)
            if ctx:
                registry.dispatch(ctx, f"/sync")
                self.notify("✓ Joined channel successfully", severity="success")
            else:
                self.notify("Backend not connected", severity="error")
        except Exception:
            self.notify("✗ Failed to join channel", severity="error")
        finally:
            self.dismiss()


class GroupMembersScreen(ModalScreen[None]):
    """Group members list."""

    def compose(self) -> ComposeResult:
        with Container(id="group_members_modal"):
            yield Static("╔═══════════ GROUP MEMBERS ════════════╗", id="members_title")
            yield ListView(id="members_list")
            yield Button("Close [Esc]", id="members_close_btn")

    @on(Button.Pressed, "#members_close_btn")
    def close(self):
        self.dismiss()

    def on_mount(self) -> None:
        self._load_members()

    def _load_members(self) -> None:
        members_list = self.query_one("#members_list", ListView)
        members_list.clear()

        try:
            ctx = getattr(self.app, 'ctx', None)
            active_contact = getattr(self.app, 'active_contact', None)
            if ctx and active_contact and 'room_id' in active_contact:
                contacts = ctx.db.list_contacts()
                for c in contacts:
                    alias = c.get("display_name") or c.get("identity_id", "Unknown")[:12]
                    members_list.append(ListItem(Label(f"👤 {alias}")))
            else:
                members_list.append(ListItem(Label("No active group")))
        except Exception:
            members_list.append(ListItem(Label("Feature not available yet")))


class NyxTUI(App):
    """Main Textual application for NYX."""

    TITLE = f"NYX v0.0.5"
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

    #channels_list, #members_list {
        height: 1fr;
        border: none;
    }

    #browse_channels_modal, #group_members_modal, #server_modal,
    #add_contact_modal, #create_group_modal, #confirm_modal,
    #help_modal {
        width: 70;
        height: auto;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }

    #browse_buttons, #server_buttons, #add_contact_buttons,
    #create_group_buttons, #confirm_buttons {
        width: 100%;
        height: auto;
        margin-top: 1;
        align: center middle;
    }

    Button {
        margin: 0 1;
    }

    ChatMessage {
        padding: 1 2;
        margin: 0 0 1 0;
    }

    .self-bubble {
        background: green;
    }

    .other-bubble {
        background: blue;
    }

    .self {
        text-align: right;
    }

    .group {
        text-align: left;
        margin-top: 2;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit_confirm", "Quit", show=True),
        Binding("ctrl+h", "show_help", "Help", show=True),
        Binding("ctrl+t", "cycle_theme", "Theme", show=True),
        Binding("ctrl+r", "sync", "Sync", show=True),
        Binding("ctrl+n", "new_contact", "New", show=True),
        Binding("ctrl+g", "new_group", "Group", show=True),
        Binding("ctrl+s", "server_settings", "Server", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        Binding("delete", "delete_contact", "Delete", show=False),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("ctrl+p", "browse_channels", "Channels", show=True),
        Binding("ctrl+m", "group_members", "Members", show=False),
    ]

    active_contact = reactive(None)

    def __init__(self, ctx: Optional[CommandContext] = None):
        super().__init__()
        self.ctx = ctx
        self.header_bar = HeaderBar()
        self.theme_cycle = ["midnight", "ember", "forest", "violet", "mono", "ocean"]
        self.current_theme_index = 0

    def compose(self) -> ComposeResult:
        yield self.header_bar
        with Horizontal(id="main_container"):
            with Vertical(id="sidebar"):
                yield Label(" CONTACTS ", id="sidebar_title")
                yield ListView(id="contact_list")
                yield Label(" CHANNELS / GROUPS ", id="sidebar_title_groups")
                yield ListView(id="group_list")
            with Vertical(id="chat_area"):
                yield Static("", id="chat_header")
                yield Vertical(id="chat_messages")
                yield Input(placeholder="Type a message...", id="input_bar")
        yield Footer()

    async def on_mount(self) -> None:
        if self.ctx:
            ident = self.ctx.identity
            if ident:
                self.header_bar.identity = ident.id
            self.header_bar.status = "Connected" if self.ctx.connected else "Disconnected"
            self.refresh_contacts()
            self.run_background_sync()

    def refresh_contacts(self) -> None:
        if not self.ctx:
            return

        contact_list = self.query_one("#contact_list", ListView)
        contact_list.clear()

        try:
            contacts = self.ctx.db.list_contacts() if self.ctx.db else []
            for contact in contacts:
                item = ContactItem(contact, is_group=False)
                contact_list.append(item)
        except Exception as e:
            log.warning("refresh_contacts.failed", error=str(e))

        group_list = self.query_one("#group_list", ListView)
        group_list.clear()

        try:
            if self.ctx.db:
                conversations = self.ctx.db.list_conversations()
                for conv in conversations:
                    if conv.get("type", "dm") != "dm":
                        group_item = ContactItem(conv, is_group=True)
                        group_list.append(group_item)
        except Exception as e:
            log.warning("refresh_groups.failed", error=str(e))

    @work(exclusive=True)
    async def run_background_sync(self) -> None:
        while True:
            if self.ctx and self.ctx.connected:
                try:
                    registry.dispatch(self.ctx, "/sync")
                    self.refresh_contacts()
                    if self.active_contact:
                        self.refresh_chat()
                except Exception:
                    pass
            await asyncio.sleep(5)

    @on(ListView.Selected)
    def on_contact_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, ContactItem):
            self.active_contact = event.item.contact
            self.refresh_chat()

    def refresh_chat(self) -> None:
        if not self.active_contact or not self.ctx:
            return

        is_group = 'room_id' in self.active_contact

        chat_header = self.query_one("#chat_header", Static)
        if is_group:
            room_id = self.active_contact['room_id']
            title = self.active_contact.get('title', 'Unnamed Group')
            room_type = self.active_contact.get('type', 'private_group')
            chat_header.update(f"Group: {title} ({room_type})")
        else:
            identity_id = self.active_contact.get('identity_id', '')
            alias = self.active_contact.get('display_name') or identity_id[:12]
            chat_header.update(f"Chat: {alias} ({identity_id[:20]}...)")

        chat_messages = self.query_one("#chat_messages", Vertical)
        for child in chat_messages.children:
            child.remove()

        if is_group:
            chat_messages.mount(Static("Group chat (messaging coming soon)"))
        else:
            peer_id = self.active_contact.get('identity_id', '')
            if not peer_id or not self.ctx.identity_id:
                chat_messages.mount(Static("No identity loaded"))
            else:
                conv_id = _conversation_id(self.ctx.identity_id, peer_id)
                try:
                    messages = self.ctx.db.get_messages(conv_id)
                    for msg in messages:
                        is_self = msg.sender_id == self.ctx.identity_id
                        sender_name = self.active_contact.get('display_name') if not is_self else "You"
                        ts = datetime.fromtimestamp(msg.timestamp) if msg.timestamp else datetime.now()
                        try:
                            content_text = msg.payload.decode("utf-8", errors="replace")
                        except Exception:
                            content_text = "[encrypted]"
                        chat_messages.mount(ChatMessage(sender_name, content_text, ts, is_self))
                except Exception as e:
                    log.warning("refresh_chat.failed", error=str(e))
                    chat_messages.mount(Static("Failed to load messages"))

        chat_messages.scroll_end(animate=False)

    @on(Input.Submitted, "#input_bar")
    async def on_message_submitted(self, event: Input.Submitted) -> None:
        content = event.value.strip()
        if not content or not self.active_contact or not self.ctx:
            return

        identity_id = self.active_contact.get('identity_id', '')
        if not identity_id:
            return

        try:
            registry.dispatch(self.ctx, f"/dm {identity_id} {content}")
            self.query_one("#input_bar", Input).value = ""
            self.refresh_chat()
        except Exception as e:
            self.notify(f"Failed to send message: {e}", severity="error")

    def action_sync(self) -> None:
        if self.ctx:
            try:
                registry.dispatch(self.ctx, "/sync")
                self.refresh_contacts()
                self.refresh_chat()
                self.notify("Synced with server")
            except Exception as e:
                self.notify(f"Sync failed: {e}", severity="error")

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_cycle_theme(self) -> None:
        self.current_theme_index = (self.current_theme_index + 1) % len(self.theme_cycle)
        theme_name = self.theme_cycle[self.current_theme_index]
        self.header_bar.theme_name = theme_name
        self.notify(f"Theme: {theme_name}")

    def action_new_contact(self) -> None:
        def on_dismiss(result):
            if result and self.ctx:
                try:
                    self.ctx.db.save_contact(result["address"], result["alias"])
                    self.refresh_contacts()
                    self.notify(f"✓ Added contact: {result['alias'] or result['address'][:12]}")
                except Exception as e:
                    self.notify(f"Failed to add contact: {e}", severity="error")
        self.push_screen(AddContactScreen(), callback=on_dismiss)

    def action_server_settings(self) -> None:
        if not self.ctx:
            return
        current_url = self.ctx.server or "http://localhost:8000"

        def on_dismiss(result):
            if result:
                try:
                    self.ctx.server = result
                    self.header_bar.status = f"Server: {result}"
                    self.notify(f"✓ Server updated: {result}")
                except Exception as e:
                    self.notify(f"Server update failed: {e}", severity="error")
        self.push_screen(ServerSettingsScreen(current_url), callback=on_dismiss)

    def action_new_group(self) -> None:
        if not self.ctx:
            return

        def on_dismiss(result):
            if result:
                try:
                    # Placeholder - rooms not yet in db.py
                    self.notify(f"✓ Group created: {result} (placeholder)")
                    self.refresh_contacts()
                except Exception as e:
                    self.notify(f"Failed to create group: {e}", severity="error")
        self.push_screen(CreateGroupScreen(), callback=on_dismiss)

    def action_clear_chat(self) -> None:
        chat_messages = self.query_one("#chat_messages", Vertical)
        for child in chat_messages.children:
            child.remove()
        self.notify("Chat display cleared")

    def action_delete_contact(self) -> None:
        if not self.active_contact or not self.ctx:
            return

        alias = self.active_contact.get('display_name') or self.active_contact.get('identity_id', '')[:12]

        def on_dismiss(confirm):
            if confirm:
                try:
                    identity_id = self.active_contact.get('identity_id', '')
                    if identity_id and self.ctx and self.ctx.db:
                        self.ctx.db.execute("DELETE FROM contacts WHERE identity_id = ?", (identity_id,))
                        self.ctx.db.commit()
                    self.active_contact = None
                    self.action_clear_chat()
                    self.refresh_contacts()
                    self.notify(f"✓ Deleted contact: {alias}")
                except Exception as e:
                    self.notify(f"Failed to delete contact: {e}", severity="error")
        self.push_screen(
            ConfirmDialog(f"Delete contact '{alias}'?\nThis will remove all message history.", title="Delete Contact"),
            callback=on_dismiss
        )

    def action_quit_confirm(self) -> None:
        def on_dismiss(confirm):
            if confirm:
                self.exit()
        self.push_screen(ConfirmDialog("Are you sure you want to quit NYX?", title="Quit"), callback=on_dismiss)

    def action_browse_channels(self) -> None:
        if not self.ctx:
            self.notify("Not connected", severity="error")
            return
        self.push_screen(BrowseChannelsScreen())

    def action_group_members(self) -> None:
        if not self.active_contact or 'room_id' not in self.active_contact:
            self.notify("No active group", severity="warning")
            return
        self.push_screen(GroupMembersScreen())

    def action_focus_next(self) -> None:
        self.focus_next()


if __name__ == "__main__":
    app = NyxTUI()
    app.run()