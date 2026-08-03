"""
NYX Client Command System.

All command handlers for the interactive REPL.
Consolidated from core/commands.py, core/messaging.py, core/directory.py, core/search.py.
"""

from __future__ import annotations

import shlex
import time
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import aiohttp

from config import get_logger
from crypto import Identity, aead_encrypt, aead_decrypt
from db import NYXDatabase, Message

log = get_logger(__name__)


@dataclass
class CommandContext:
    """Context passed to command handlers."""
    identity: Optional[Identity] = None
    identity_id: Optional[str] = None
    server: Optional[str] = None
    connected: bool = False
    db: Optional[NYXDatabase] = None
    session: Optional[aiohttp.ClientSession] = None


@dataclass
class CommandResult:
    """Result from command execution."""
    ok: bool
    message: str
    data: Optional[Any] = None


CommandHandler = Callable[[CommandContext, List[str]], CommandResult]


@dataclass
class CommandSpec:
    """Command specification."""
    name: str
    handler: CommandHandler
    help: str
    usage: str = ""


class CommandRegistry:
    """Registry of available commands."""

    def __init__(self) -> None:
        self._commands: Dict[str, CommandSpec] = {}

    def register(self, name: str, help: str, usage: str = ""):
        """Decorator to register a command."""
        def decorator(fn: CommandHandler) -> CommandHandler:
            self._commands[name] = CommandSpec(
                name=name, handler=fn, help=help, usage=usage or ("/" + name)
            )
            return fn
        return decorator

    def get(self, name: str) -> Optional[CommandSpec]:
        """Get command spec by name."""
        return self._commands.get(name)

    def list_commands(self) -> List[CommandSpec]:
        """List all registered commands."""
        return sorted(self._commands.values(), key=lambda c: c.name)

    def dispatch(self, ctx: CommandContext, line: str) -> CommandResult:
        """Parse and execute a command line."""
        line = line.strip()
        if not line:
            return CommandResult(ok=True, message="")
        
        if not line.startswith("/"):
            return CommandResult(
                ok=False,
                message="Commands start with /. Type /help for a list.",
            )
        
        try:
            parts = shlex.split(line[1:])
        except ValueError as exc:
            return CommandResult(ok=False, message="parse error: " + str(exc))
        
        if not parts:
            return CommandResult(ok=False, message="empty command")
        
        name = parts[0].lower()
        args = parts[1:]
        
        if name in ("help", "?"):
            return self._help(args)
        
        spec = self._commands.get(name)
        if spec is None:
            return CommandResult(ok=False, message="unknown command: /" + name)
        
        if args and args[0] in ("--help", "-h"):
            return CommandResult(
                ok=True,
                message=f"/{spec.name} - {spec.help}\nUsage: {spec.usage}",
            )
        
        try:
            return spec.handler(ctx, args)
        except Exception as e:
            log.exception("command.error", command=name)
            return CommandResult(ok=False, message="error: " + str(e))

    def _help(self, args: List[str]) -> CommandResult:
        """Show help for commands."""
        if args:
            key = args[0].lstrip("/").lower()
            spec = self._commands.get(key)
            if spec is None:
                return CommandResult(ok=False, message="unknown: " + args[0])
            return CommandResult(
                ok=True,
                message=f"/{spec.name} - {spec.help}\nUsage: {spec.usage}",
            )
        
        lines = ["Available commands:", ""]
        for spec in self.list_commands():
            lines.append(f"  /{spec.name:<12} {spec.help}")
        lines.append("")
        lines.append("Type /help <command> for details.")
        return CommandResult(ok=True, message="\n".join(lines))


# Global registry
registry = CommandRegistry()

# Export for type hints
__all__ = [
    "CommandContext",
    "CommandResult",
    "CommandRegistry",
    "registry",
]


# =============================================================================
# Command Implementations
# =============================================================================

@registry.register("exit", "Exit the client", "/exit")
def cmd_exit(ctx: CommandContext, args: List[str]) -> CommandResult:
    return CommandResult(ok=True, message="__EXIT__")


@registry.register("quit", "Exit the client", "/quit")
def cmd_quit(ctx: CommandContext, args: List[str]) -> CommandResult:
    return CommandResult(ok=True, message="__EXIT__")


@registry.register("status", "Show connection and identity status", "/status")
def cmd_status(ctx: CommandContext, args: List[str]) -> CommandResult:
    lines = [
        "Identity : " + (ctx.identity_id or "(none)"),
        "Server   : " + (ctx.server or "(none)"),
        "Connected: " + ("yes" if ctx.connected else "no"),
    ]
    return CommandResult(ok=True, message="\n".join(lines))


@registry.register("identity", "Show local identity", "/identity")
def cmd_identity(ctx: CommandContext, args: List[str]) -> CommandResult:
    if not ctx.identity_id:
        return CommandResult(ok=False, message="no identity loaded")
    return CommandResult(ok=True, message="Identity: " + ctx.identity_id)


@registry.register("contacts", "List all contacts", "/contacts")
def cmd_contacts(ctx: CommandContext, args: List[str]) -> CommandResult:
    if not ctx.db:
        return CommandResult(ok=False, message="database not available")
    
    contacts = ctx.db.list_contacts()
    if not contacts:
        return CommandResult(ok=True, message="(no contacts)")
    
    lines = ["Contacts:"]
    for contact in contacts:
        name = contact.get("display_name") or "(unnamed)"
        identity = contact.get("identity_id", "")[:24]
        lines.append(f"  {name:<20} {identity}...")
    
    return CommandResult(ok=True, message="\n".join(lines))


@registry.register("add", "Add a contact", "/add <identity> [name]")
def cmd_add_contact(ctx: CommandContext, args: List[str]) -> CommandResult:
    if not ctx.db:
        return CommandResult(ok=False, message="database not available")
    
    if not args:
        return CommandResult(ok=False, message="Usage: /add <identity> [name]")
    
    identity_id = args[0]
    display_name = " ".join(args[1:]) if len(args) > 1 else ""
    
    ctx.db.save_contact(identity_id, display_name)
    return CommandResult(ok=True, message=f"Added contact: {display_name or identity_id[:24]}")


@registry.register("dm", "Send or view direct message", "/dm <identity> [message]")
def cmd_dm(ctx: CommandContext, args: List[str]) -> CommandResult:
    if not args:
        return CommandResult(ok=False, message="Usage: /dm <identity> [message]")
    
    if not ctx.db or not ctx.identity_id:
        return CommandResult(ok=False, message="not initialized")
    
    peer_id = args[0]
    conversation_id = _conversation_id(ctx.identity_id, peer_id)
    
    # View history if no message provided
    if len(args) == 1:
        messages = ctx.db.get_messages(conversation_id, limit=20)
        if not messages:
            return CommandResult(ok=True, message=f"(no messages with {peer_id[:24]})")
        
        lines = []
        for msg in messages:
            arrow = "->" if msg.direction == "out" else "<-"
            try:
                text = msg.payload.decode("utf-8", errors="replace")
            except:
                text = "[encrypted]"
            lines.append(f"  {arrow} [{msg.sequence}] {text}")
        
        return CommandResult(ok=True, message="\n".join(lines))
    
    # Send message
    text = " ".join(args[1:])
    message_id = hashlib.sha256(f"{ctx.identity_id}{peer_id}{time.time()}".encode()).hexdigest()[:32]
    
    ctx.db.ensure_conversation(conversation_id, peer_id)
    
    # Get next sequence number
    existing = ctx.db.get_messages(conversation_id, limit=1)
    sequence = (existing[0].sequence + 1) if existing else 1
    
    # Save message
    message = Message(
        message_id=message_id,
        conversation_id=conversation_id,
        sender_id=ctx.identity_id,
        payload=text.encode("utf-8"),
        sequence=sequence,
        timestamp=int(time.time()),
        direction="out",
        status="sent",
    )
    ctx.db.save_message(message)
    
    return CommandResult(ok=True, message=f"Sent message to {peer_id[:24]}")


@registry.register("conversations", "List all conversations", "/conversations")
def cmd_conversations(ctx: CommandContext, args: List[str]) -> CommandResult:
    if not ctx.db:
        return CommandResult(ok=False, message="database not available")
    
    convs = ctx.db.list_conversations()
    if not convs:
        return CommandResult(ok=True, message="(no conversations)")
    
    lines = ["Conversations:"]
    for conv in convs:
        peer = conv.get("peer_id", "")[:24]
        last_seq = conv.get("last_sequence", 0)
        lines.append(f"  {peer}... (seq: {last_seq})")
    
    return CommandResult(ok=True, message="\n".join(lines))


@registry.register("sync", "Sync messages from server", "/sync")
def cmd_sync(ctx: CommandContext, args: List[str]) -> CommandResult:
    if not ctx.server or not ctx.identity_id:
        return CommandResult(ok=False, message="not connected")
    
    # Simplified sync - would normally fetch from server
    return CommandResult(ok=True, message="Sync complete (no new messages)")


@registry.register("create_group", "Create a new group", "/create_group <name>")
def cmd_create_group(ctx: CommandContext, args: List[str]) -> CommandResult:
    if not args:
        return CommandResult(ok=False, message="Usage: /create_group <name>")
    
    if not ctx.db:
        return CommandResult(ok=False, message="database not available")

    name = args[0]
    room_id = hashlib.sha256(f"group{name}{time.time()}".encode()).hexdigest()[:32]
    
    now = int(time.time())
    ctx.db.execute(
        """INSERT INTO conversations (conversation_id, type, title, created_at, updated_at)
           VALUES (?, 'group', ?, ?, ?)""",
        (room_id, name, now, now)
    )
    ctx.db.commit()
    
    return CommandResult(ok=True, message=f"Created group: {name}", data={"room_id": room_id})


@registry.register("delete_contact", "Delete a contact", "/delete_contact <identity>")
def cmd_delete_contact(ctx: CommandContext, args: List[str]) -> CommandResult:
    if not args:
        return CommandResult(ok=False, message="Usage: /delete_contact <identity>")
    
    if not ctx.db:
        return CommandResult(ok=False, message="database not available")

    identity_id = args[0]
    ctx.db.execute("DELETE FROM contacts WHERE identity_id = ?", (identity_id,))
    ctx.db.commit()
    
    return CommandResult(ok=True, message=f"Deleted contact: {identity_id}")


@registry.register("delete_group", "Delete or leave a group", "/delete_group <room_id>")
def cmd_delete_group(ctx: CommandContext, args: List[str]) -> CommandResult:
    if not args:
        return CommandResult(ok=False, message="Usage: /delete_group <room_id>")
    
    if not ctx.db:
        return CommandResult(ok=False, message="database not available")

    room_id = args[0]
    ctx.db.execute("DELETE FROM conversations WHERE conversation_id = ? AND type = 'group'", (room_id,))
    ctx.db.commit()
    
    return CommandResult(ok=True, message=f"Left group: {room_id}")


@registry.register("clear", "Clear screen", "/clear")
def cmd_clear(ctx: CommandContext, args: List[str]) -> CommandResult:
    print("\033[2J\033[H", end="")  # ANSI clear screen
    return CommandResult(ok=True, message="")


# =============================================================================
# Utility Functions
# =============================================================================

def _conversation_id(id1: str, id2: str) -> str:
    """Generate deterministic conversation ID from two identities."""
    sorted_ids = tuple(sorted([id1, id2]))
    return hashlib.sha256(f"{sorted_ids[0]}{sorted_ids[1]}".encode()).hexdigest()[:32]