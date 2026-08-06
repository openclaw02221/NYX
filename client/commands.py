import argparse
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Any, List
import requests
import json

@dataclass
class CommandResult:
    """Result from a command execution"""
    ok: bool
    message: str
    data: Optional[Any] = None

@dataclass
class CommandContext:
    """Context passed to all commands"""
    identity: Any  # Identity object
    identity_id: str  # Identity ID as string
    server: str  # Server URL
    connected: bool  # Connection status
    db: Any  # NYXDatabase instance
    
    def is_connected(self) -> bool:
        """Check if connected to server"""
        return self.connected
    
    def get_identity_id(self) -> str:
        """Get current identity ID"""
        return self.identity_id
    
    def get_server_url(self) -> str:
        """Get current server URL"""
        return self.server
    
    def update_connection_status(self, status: bool):
        """Update connection status"""
        self.connected = status


class Command:
    """Base class for commands"""
    def __init__(self, name: str, handler: Callable, help_text: str = ""):
        self.name = name
        self.handler = handler
        self.help_text = help_text
        self.parser = argparse.ArgumentParser(
            prog=name,
            description=help_text,
            add_help=False
        )
    
    def execute(self, ctx: CommandContext, args: list[str]) -> str:
        """Execute the command"""
        try:
            parsed = self.parser.parse_args(args)
            return self.handler(ctx, parsed)
        except SystemExit:
            return f"Invalid arguments for {self.name}"
        except Exception as e:
            return f"Error: {str(e)}"


class CommandRegistry:
    """Registry for all commands"""
    def __init__(self):
        self.commands: Dict[str, Command] = {}
    
    def register(self, name: str, handler: Callable, help_text: str = ""):
        """Register a command"""
        cmd = Command(name, handler, help_text)
        self.commands[name] = cmd
        return cmd
    
    def get(self, name: str) -> Optional[Command]:
        """Get a command by name"""
        return self.commands.get(name)
    
    def list_commands(self) -> list[str]:
        """List all registered commands"""
        return list(self.commands.keys())
    
    def execute(self, ctx: CommandContext, command: str, args: list[str]) -> str:
        """Execute a command"""
        cmd = self.get(command)
        if not cmd:
            return f"Unknown command: {command}"
        return cmd.execute(ctx, args)
    
    def dispatch(self, ctx: CommandContext, line: str) -> CommandResult:
        """Parse and dispatch a command line (for ui.py compatibility)"""
        line = line.strip()
        if not line:
            return CommandResult(ok=True, message="")
        
        if not line.startswith("/"):
            return CommandResult(ok=False, message="Commands must start with /")
        
        # Remove leading / and split
        parts = line[1:].split(None, 1)
        if not parts:
            return CommandResult(ok=False, message="Empty command")
        
        command = parts[0].lower()
        args = parts[1].split() if len(parts) > 1 else []
        
        # Handle special exit/quit commands
        if command in ("exit", "quit"):
            return CommandResult(ok=True, message="EXIT")
        
        # Execute command
        result_message = self.execute(ctx, command, args)
        
        # Check if result indicates exit
        if result_message == "QUIT":
            return CommandResult(ok=True, message="EXIT")
        
        # Return result
        is_error = result_message.startswith("Error:") or result_message.startswith("Unknown command")
        return CommandResult(ok=not is_error, message=result_message)


# Global registry
registry = CommandRegistry()


# Command handlers
def cmd_help(ctx: CommandContext, args: argparse.Namespace) -> str:
    """Show help"""
    commands = registry.list_commands()
    return "Available commands:\n" + "\n".join(f"  {cmd}" for cmd in sorted(commands))


def cmd_connect(ctx: CommandContext, args: argparse.Namespace) -> str:
    """Connect to server"""
    try:
        response = requests.get(f"{ctx.server}/api/v3/health", timeout=5)
        if response.status_code == 200:
            ctx.update_connection_status(True)
            return f"Connected to {ctx.server}"
        return f"Failed to connect: {response.status_code}"
    except Exception as e:
        ctx.update_connection_status(False)
        return f"Connection failed: {str(e)}"


def cmd_register(ctx: CommandContext, args: argparse.Namespace) -> str:
    """Register identity on server"""
    if not ctx.is_connected():
        return "Not connected. Use /connect first."
    
    try:
        public_key = ctx.identity.public_key_bytes.hex()
        data = {
            'identity_id': ctx.identity_id,
            'public_key': public_key
        }
        response = requests.post(
            f"{ctx.server}/register.php",
            json=data,
            timeout=10
        )
        if response.status_code == 200:
            return "Registration successful"
        return f"Registration failed: {response.text}"
    except Exception as e:
        return f"Registration error: {str(e)}"


def cmd_contacts(ctx: CommandContext, args: argparse.Namespace) -> str:
    """List contacts"""
    contacts = ctx.db.list_contacts()
    if not contacts:
        return "No contacts"
    
    result = ["Contacts:"]
    for contact in contacts:
        result.append(f"  {contact['name']} ({contact['identity_id']})")
    return "\n".join(result)


def cmd_add_contact(ctx: CommandContext, args: argparse.Namespace) -> str:
    """Add a contact"""
    if not args.name or not args.identity_id:
        return "Usage: /add <name> <identity_id>"
    
    ctx.db.save_contact(args.name, args.identity_id, args.public_key or "")
    return f"Added contact: {args.name}"


def cmd_conversations(ctx: CommandContext, args: argparse.Namespace) -> str:
    """List conversations"""
    convs = ctx.db.list_conversations()
    if not convs:
        return "No conversations"
    
    result = ["Conversations:"]
    for conv in convs:
        result.append(f"  {conv['conversation_id']}: {conv['participant_count']} participants")
    return "\n".join(result)


def cmd_send(ctx: CommandContext, args: argparse.Namespace) -> str:
    """Send a message"""
    if not args.recipient or not args.message:
        return "Usage: /send <recipient_id> <message>"
    
    if not ctx.is_connected():
        return "Not connected. Use /connect first."
    
    try:
        # Ensure conversation exists
        conv_id = ctx.db.ensure_conversation([ctx.identity_id, args.recipient])
        
        # Save message locally
        ctx.db.save_message(conv_id, ctx.identity_id, args.recipient, args.message)
        
        # Send to server
        data = {
            'from_id': ctx.identity_id,
            'to_id': args.recipient,
            'content': args.message
        }
        response = requests.post(
            f"{ctx.server}/send.php",
            json=data,
            timeout=10
        )
        if response.status_code == 200:
            return f"Message sent to {args.recipient}"
        return f"Send failed: {response.text}"
    except Exception as e:
        return f"Send error: {str(e)}"


def cmd_messages(ctx: CommandContext, args: argparse.Namespace) -> str:
    """Show messages"""
    if not args.conversation_id:
        return "Usage: /messages <conversation_id>"
    
    messages = ctx.db.get_messages(args.conversation_id)
    if not messages:
        return f"No messages in conversation {args.conversation_id}"
    
    result = [f"Messages in {args.conversation_id}:"]
    for msg in messages:
        result.append(f"  [{msg['timestamp']}] {msg['from_id']}: {msg['content']}")
    return "\n".join(result)


def cmd_sync(ctx: CommandContext, args: argparse.Namespace) -> str:
    """Sync messages from server"""
    if not ctx.is_connected():
        return "Not connected. Use /connect first."
    
    try:
        response = requests.post(
            f"{ctx.server}/sync.php",
            json={'identity_id': ctx.identity_id},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            count = len(data.get('messages', []))
            return f"Synced {count} messages"
        return f"Sync failed: {response.text}"
    except Exception as e:
        return f"Sync error: {str(e)}"


def cmd_status(ctx: CommandContext, args: argparse.Namespace) -> str:
    """Show status"""
    status = "connected" if ctx.is_connected() else "disconnected"
    return f"Identity: {ctx.identity_id}\nServer: {ctx.server}\nStatus: {status}"


def cmd_quit(ctx: CommandContext, args: argparse.Namespace) -> str:
    """Quit the application"""
    return "QUIT"


# Register commands
registry.register("help", cmd_help, "Show help")
registry.register("connect", cmd_connect, "Connect to server")
registry.register("register", cmd_register, "Register on server")
registry.register("contacts", cmd_contacts, "List contacts")
registry.register("conversations", cmd_conversations, "List conversations")
registry.register("status", cmd_status, "Show status")
registry.register("sync", cmd_sync, "Sync messages")
registry.register("quit", cmd_quit, "Quit")
registry.register("exit", cmd_quit, "Exit")

# Register commands that need argument configuration
cmd_add = registry.register("add", cmd_add_contact, "Add contact")
cmd_add.parser.add_argument("name", help="Contact name")
cmd_add.parser.add_argument("identity_id", help="Contact identity ID")
cmd_add.parser.add_argument("--public-key", dest="public_key", help="Public key")

cmd_send = registry.register("send", cmd_send, "Send message")
cmd_send.parser.add_argument("recipient", help="Recipient identity ID")
cmd_send.parser.add_argument("message", nargs="+", help="Message to send")

cmd_messages = registry.register("messages", cmd_messages, "Show messages")
cmd_messages.parser.add_argument("conversation_id", help="Conversation ID")
