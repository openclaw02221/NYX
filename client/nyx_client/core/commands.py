"""
commands.py — Command implementations for the NYX Messenger REPL.

Each function performs one user action (register, send, sync, etc.).
All errors are printed locally and never raise out of the REPL.
No sys.exit() calls — the REPL must keep running.

Messages are displayed in real-time but NOT persisted to the database
(session-only chat history by design).
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from nyx_client import config
from nyx_client import crypto
from nyx_client import ui
from nyx_client.core import messaging
from nyx_client.storage import NYXDatabase
from nyx_client.themes import ThemeManager, THEMES

# ---------------------------------------------------------------------------
# Theme manager injection (delegates to messaging module for shared state)
# ---------------------------------------------------------------------------

def set_theme_manager(tm: ThemeManager) -> None:
    """Inject the shared ThemeManager used for styled output."""
    messaging.set_theme_manager(tm)


def _tm_or_default() -> ThemeManager:
    return messaging._tm_or_default()


# ---------------------------------------------------------------------------
# Output helpers (delegate to messaging / ui)
# ---------------------------------------------------------------------------

def _error(msg: str) -> None:
    messaging._error(msg)


def _info(msg: str) -> None:
    messaging._info(msg)


def _success(msg: str) -> None:
    messaging._success(msg)


def _warning(msg: str) -> None:
    messaging._warning(msg)


# Re-export messaging functions so callers can use commands.sync_messages etc.
sync_messages = messaging.sync_messages
send_message = messaging.send_message
get_session_messages = messaging.get_session_messages
clear_session_messages = messaging.clear_session_messages


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def show_help() -> None:
    """Print the help screen in plain text."""
    print()
    print("=== NYX Commands ===")
    print()
    help_lines = [
        ("/help", "Show this help message"),
        ("/switch <contact>", "Set active chat target (alias or device ID)"),
        ("/chat <contact>", "Alias for /switch"),
        ("/contacts", "List known contacts"),
        ("/contacts --sort alias|id", "List contacts sorted by alias or device ID"),
        ("/send <contact> <msg>", "Send an encrypted message directly"),
        ("/sync", "Pull new messages from the server (manual)"),
        ("/sync on|off", "Enable / disable background auto-sync"),
        ("/sync interval <N>", "Set auto-sync interval in seconds"),
        ("/sync status", "Show current sync settings"),
        ("/import <public_key>", "Import a contact's public key"),
        ("/alias <id> <name>", "Set or change a contact alias"),
        ("/theme <name>|list", "Change or list colour themes"),
        ("/server [url]", "View or set the relay server URL"),
        ("/config [key] [value]", "View or set configuration"),
        ("/clear", "Clear the terminal screen"),
        ("/myid", "Show your device ID and public key"),
        ("/register", "Register your identity with the relay server"),
        ("/debug", "Show debug information"),
        ("/quit or /exit", "Exit NYX"),
    ]
    for cmd, desc in help_lines:
        print(f"  {cmd:<28} {desc}")
    print()
    print("=== True Chat CLI Experience ===")
    print("  1. Select a contact:  /switch Alice")
    print("  2. Type directly:     Hello Alice, how are you?")
    print("  3. Commands start with '/': e.g. /help, /contacts, /clear")
    print()


def register(
    cfg: config.NYXConfig,
    local_db: NYXDatabase,
    crypto_engine: crypto.NYXCrypto,
    quiet: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Register this device's public key with the relay server.
    Generates a new identity if one doesn't exist yet.
    """
    if not crypto_engine.has_identity():
        crypto_engine.generate_identity()

    device_id = crypto_engine.device_id
    public_key = crypto_engine.get_public_key_b64()

    if not quiet:
        _info(f"Registering device {device_id}...")

    resp = messaging.post(cfg, "register.php", {
        "device_id": device_id,
        "public_key": public_key,
    })

    if resp is None:
        if not quiet:
            _error("Registration failed — server unreachable.")
        return None

    if resp.get("status") == "ok":
        if not quiet:
            _success("Registered successfully.")
        local_db.save_identity(device_id, public_key)
    else:
        if not quiet:
            _error(f"Registration rejected: {resp.get('error', 'unknown error')}")

    return resp


def show_my_id(crypto_engine: crypto.NYXCrypto) -> None:
    """Display the local device identity."""
    device_id = crypto_engine.device_id
    public_key = crypto_engine.get_public_key_b64()

    print()
    print("Device Identity")
    print(f"  Device ID:    {device_id}")
    print(f"  Public Key:   {public_key}")
    print(f"  Key length:   {len(public_key)} chars (base64, 64 raw bytes)")
    print()
    print("Copy the full public key above to share with other NYX users.")
    print()


def list_contacts(
    local_db: NYXDatabase,
    sort_by: str = "id",
) -> None:
    """Display all known contacts with aliases."""
    contacts = local_db.get_contacts(sort_by=sort_by)
    ui.print_contacts_table(contacts, sort_by=sort_by, tm=_tm_or_default())


def import_contact(
    local_db: NYXDatabase,
    public_key_b64: str,
    alias: Optional[str] = None,
    prompt_alias: bool = True,
) -> Optional[str]:
    """
    Import a contact by their public key bundle.

    Accepts the 88-character base64 bundle (the exact output of '/myid').
    Optionally prompts for an alias if prompt_alias is True and alias is None.
    Returns the derived device_id on success, or None on failure.
    """
    try:
        ed_pub, x_pub = crypto.parse_public_key_bundle(public_key_b64.strip())
    except Exception:
        _error("Invalid public key format.")
        return None

    device_id = hashlib.sha256(ed_pub).hexdigest()[:16]

    # Optional alias prompt
    if prompt_alias and alias is None:
        try:
            from prompt_toolkit import prompt as pt_prompt
            raw = pt_prompt(
                "Enter alias (optional, press Enter to skip): "
            ).strip()
            if raw:
                alias = raw
        except (KeyboardInterrupt, EOFError):
            print()
        except Exception:
            pass

    local_db.save_contact(device_id, public_key_b64.strip(), alias=alias)

    if alias:
        _success(f"Contact imported — device_id: {device_id}, alias: {alias}")
    else:
        _success(f"Contact imported — device_id: {device_id}")

    print(f"  Ed25519: {ed_pub.hex()[:32]}...")
    print(f"  X25519:  {x_pub.hex()[:32]}...")
    return device_id


def set_alias(
    local_db: NYXDatabase,
    device_id_or_name: str,
    alias: str,
) -> None:
    """Set or change the alias for a contact."""
    resolved = local_db.resolve_contact(device_id_or_name)
    if not resolved:
        if local_db.get_contact(device_id_or_name):
            resolved = device_id_or_name
        else:
            _error(f"Unknown contact: {device_id_or_name}")
            return

    ok = local_db.update_alias(resolved, alias)
    if ok:
        if alias.strip():
            _success(f"Alias for {resolved} set to '{alias.strip()}'.")
        else:
            _success(f"Alias for {resolved} cleared.")
    else:
        _error(f"Failed to update alias for {device_id_or_name}.")


def handle_sync_command(
    cfg: config.NYXConfig,
    local_db: NYXDatabase,
    crypto_engine: crypto.NYXCrypto,
    args: str,
) -> None:
    """
    Handle the multi-form `sync` command:

      /sync              — manual pull
      /sync on           — enable auto-sync
      /sync off          — disable auto-sync
      /sync interval N   — set interval seconds
      /sync status       — show settings
    """
    parts = args.split() if args else []

    if not parts:
        # Manual sync
        since = local_db.get_last_sync_time()
        result = sync_messages(cfg, local_db, crypto_engine, since=since)
        if result and result.get("messages"):
            last_times = [
                m.get("created_at", "")
                for m in result["messages"]
                if m.get("created_at")
            ]
            if last_times:
                local_db.set_last_sync_time(max(last_times))
        return

    sub = parts[0].lower()

    if sub == "on":
        cfg.set("auto_sync", True)
        _success("Auto-sync enabled.")
    elif sub == "off":
        cfg.set("auto_sync", False)
        _success("Auto-sync disabled.")
    elif sub == "interval":
        if len(parts) < 2:
            _error("Usage: /sync interval <seconds>")
            return
        try:
            n = int(parts[1])
            if n < 1:
                raise ValueError("must be >= 1")
            cfg.set("sync_interval", n)
            _success(f"Sync interval set to {n} second(s).")
        except ValueError:
            _error("Interval must be a positive integer.")
    elif sub == "status":
        print()
        print("Sync Settings")
        print(f"  Auto-sync:     {'ON' if cfg.auto_sync else 'OFF'}")
        print(f"  Interval:      {cfg.sync_interval}s")
        last = local_db.get_last_sync_time()
        print(f"  Last sync:     {last or 'never'}")
        print()
    else:
        _error(f"Unknown sync subcommand: {sub}")
        _info("Usage: /sync [on|off|interval <N>|status]")


def handle_theme_command(cfg: config.NYXConfig, args: str) -> None:
    """
    Handle theme commands:

      /theme list
      /theme <name>
      /theme            (show current)
    """
    parts = args.split() if args else []

    if not parts or parts[0].lower() == "list":
        print()
        print("Available themes:")
        current = cfg.theme
        for name in sorted(THEMES.keys()):
            marker = " (active)" if name == current else ""
            print(f"  • {name}{marker}")
        print()
        return

    name = parts[0].lower()
    if name not in THEMES:
        _error(f"Unknown theme: {name}")
        _info(f"Available: {', '.join(sorted(THEMES.keys()))}")
        return

    cfg.set("theme", name)
    if messaging._tm is not None:
        messaging._tm.set_theme(name)
    _success(f"Theme set to '{name}'.")


def set_config(cfg: config.NYXConfig, key: str, value: str) -> None:
    """Set a configuration value."""
    allowed = {
        "server_url": str,
        "auto_sync": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
        "sync_interval": int,
        "theme": str,
    }
    if key not in allowed:
        _error(f"Unknown config key: {key}")
        _info(f"Allowed keys: {', '.join(sorted(allowed.keys()))}")
        return

    if key == "auto_sync":
        parsed: Any = str(value).lower() in ("1", "true", "yes", "on")
    elif key == "sync_interval":
        try:
            parsed = max(1, int(value))
        except ValueError:
            _error("sync_interval must be an integer.")
            return
    elif key == "theme":
        if value.lower() not in THEMES:
            _error(f"Unknown theme: {value}")
            return
        parsed = value.lower()
        if messaging._tm is not None:
            messaging._tm.set_theme(parsed)
    else:
        parsed = value

    cfg.set(key, parsed)
    _success(f"{key} = {parsed}")


def show_debug_info(
    crypto_engine: crypto.NYXCrypto,
    local_db: NYXDatabase,
    cfg: config.NYXConfig,
) -> None:
    """Show debug information about the current state."""
    print()
    print("Debug Information")
    lines = [
        f"  Version:        {config.VERSION}",
        f"  Config path:    {cfg.config_path}",
        f"  Server URL:     {cfg.server_url}",
        f"  DB path:        {cfg.db_path}",
        f"  Device ID:      {crypto_engine.device_id}",
        f"  Has identity:   {crypto_engine.has_identity()}",
        f"  Registered:     {local_db.is_registered()}",
        f"  Contacts:       {len(local_db.get_contacts())}",
        f"  Auto-sync:      {cfg.auto_sync}",
        f"  Sync interval:  {cfg.sync_interval}s",
        f"  Theme:          {cfg.theme}",
        f"  Session msgs:   {messaging.session_message_count()}",
    ]
    for line in lines:
        print(line)
    print()