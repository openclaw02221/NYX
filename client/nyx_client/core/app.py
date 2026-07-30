"""
app.py — Application state and lifecycle for the NYX Messenger client.

Holds global runtime state (active contact, sync thread, message queue)
and provides the command dispatcher used by the REPL.
"""

from __future__ import annotations

import os
import threading
import traceback
from collections import deque
from typing import Optional

from nyx_client import config
from nyx_client import crypto
from nyx_client import ui
from nyx_client.core import commands
from nyx_client.storage import NYXDatabase
from nyx_client.themes import ThemeManager

# ── Global state ───────────────────────────────────────────────────────────
running = True
sync_thread: Optional[threading.Thread] = None
active_contact: Optional[str] = None     # resolved device_id of active chat
active_contact_display: Optional[str] = None  # alias or short device_id
theme_manager: Optional[ThemeManager] = None
# Event used to wake the sync thread early when interval/settings change
sync_wake = threading.Event()

# Thread-safe message queue for sync thread → main thread communication.
# Using a deque with a lock ensures prompt_toolkit never prints from a
# background thread without coordination.
_message_queue: deque = deque()
_message_lock = threading.Lock()

# Track displayed messages by timestamp+content hash to avoid duplicates
# when a manual sync overlaps with auto-sync.
_displayed_hashes: set = set()


# ---------------------------------------------------------------------------
# Background sync helpers
# ---------------------------------------------------------------------------

def push_message(timestamp: str, sender: str, content: str, is_you: bool) -> None:
    """Push a chat message onto the thread-safe queue for main-thread display."""
    msg_hash = hash((timestamp, sender, content, is_you))
    with _message_lock:
        if msg_hash not in _displayed_hashes:
            _displayed_hashes.add(msg_hash)
            _message_queue.append((timestamp, sender, content, is_you))


def flush_message_queue() -> None:
    """
    Called from the main REPL loop to display any queued messages.
    This runs on the main thread, safe for prompt_toolkit.
    Uses plain print() because we're inside patch_stdout().
    """
    with _message_lock:
        while _message_queue:
            ts, sender, content, is_you = _message_queue.popleft()
            line = f"[{ts}] "
            if is_you:
                line += f"You: {content}"
            else:
                line += f"{sender}: {content}"
            print(line)


def background_sync(
    cfg: config.NYXConfig,
    local_db: NYXDatabase,
    crypto_engine: crypto.NYXCrypto,
) -> None:
    """
    Background thread: pulls new messages periodically and queues them
    for thread-safe display on the main REPL loop.

    Uses a message queue + main-thread flush to avoid garbling the
    prompt_toolkit input line.
    """
    global running

    while running:
        try:
            if cfg.auto_sync:
                since = local_db.get_last_sync_time()
                result = commands.sync_messages(
                    cfg,
                    local_db,
                    crypto_engine,
                    since=since,
                    quiet=True,       # no "No new messages" spam
                    notify=False,     # we handle display via queue
                    push_fn=push_message,  # thread-safe queue callback
                )
                if result and result.get("messages"):
                    last_times = [
                        m.get("created_at", "")
                        for m in result["messages"]
                        if m.get("created_at")
                    ]
                    if last_times:
                        local_db.set_last_sync_time(max(last_times))
        except Exception:
            # Never crash the REPL from the sync thread
            if os.environ.get("NYX_DEBUG"):
                traceback.print_exc()

        # Sleep in small slices so we can exit promptly and react to
        # interval changes / wake events.
        interval = cfg.sync_interval
        slices = max(1, int(interval * 10))
        for _ in range(slices):
            if not running:
                return
            if sync_wake.wait(timeout=0.1):
                sync_wake.clear()
                break


# ---------------------------------------------------------------------------
# Smart command dispatcher
# ---------------------------------------------------------------------------

def process_command(
    line: str,
    cfg: config.NYXConfig,
    local_db: NYXDatabase,
    crypto_engine: crypto.NYXCrypto,
) -> bool:
    """
    Smart input parser:
      - Lines starting with '/' → command dispatcher
      - Bare text with active_contact → auto-send to active contact
      - Bare text without active_contact → show helpful message

    Returns False if the user wants to quit.
    """
    global running, active_contact, active_contact_display

    stripped = line.strip()
    if not stripped:
        return True

    # ── SMART PARSING ──
    # CASE 1: Input starts with '/' → it's a command
    if stripped.startswith("/"):
        return handle_command(
            stripped, cfg, local_db, crypto_engine
        )

    # CASE 2: Input does NOT start with '/', and we have an active contact
    #         → auto-send as a message
    if active_contact:
        commands.send_message(
            cfg, local_db, crypto_engine, active_contact, stripped
        )
        return True

    # CASE 3: Input does NOT start with '/', no active contact
    #         → tell the user how to start chatting
    ui.print_info(
        "No active chat. Use '/switch <contact>' to start chatting, "
        "or type '/help'.",
        theme_manager,
    )
    return True


def handle_command(
    stripped: str,
    cfg: config.NYXConfig,
    local_db: NYXDatabase,
    crypto_engine: crypto.NYXCrypto,
) -> bool:
    """
    Parse and execute a command string (already confirmed to start with '/').
    """
    global running, active_contact, active_contact_display

    # Strip the leading '/'
    cmd_text = stripped[1:].lstrip()
    if not cmd_text:
        return True

    parts = cmd_text.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    try:
        if cmd in ("quit", "exit", "q"):
            ui.print_info("Goodbye. Stay encrypted.", theme_manager)
            running = False
            return False

        elif cmd in ("help", "?"):
            commands.show_help()

        elif cmd == "register":
            commands.register(cfg, local_db, crypto_engine)

        elif cmd == "myid":
            commands.show_my_id(crypto_engine)

        elif cmd == "sync":
            commands.handle_sync_command(cfg, local_db, crypto_engine, args)
            sync_wake.set()

        elif cmd == "send":
            if not args:
                ui.print_error(
                    "Usage: /send <contact> <message>", theme_manager
                )
            else:
                send_parts = args.split(maxsplit=1)
                if len(send_parts) < 2:
                    ui.print_error(
                        "Usage: /send <contact> <message>", theme_manager
                    )
                else:
                    commands.send_message(
                        cfg, local_db, crypto_engine,
                        send_parts[0], send_parts[1],
                    )

        elif cmd in ("switch", "chat"):
            if not args:
                if active_contact:
                    ui.print_info(
                        f"Active contact: {active_contact_display} "
                        f"({active_contact})",
                        theme_manager,
                    )
                else:
                    ui.print_info(
                        "No active contact. "
                        "Usage: /switch <alias_or_id>",
                        theme_manager,
                    )
            else:
                name = args.strip()
                if name.lower() in ("none", "off", "-"):
                    active_contact = None
                    active_contact_display = None
                    ui.print_success("Active contact cleared.", theme_manager)
                else:
                    resolved = local_db.resolve_contact(name)
                    if not resolved:
                        ui.print_error(
                            f"Unknown contact: {name}", theme_manager
                        )
                    else:
                        active_contact = resolved
                        active_contact_display = local_db.display_name(resolved)
                        ui.print_success(
                            f"Now chatting with {active_contact_display} "
                            f"({resolved})",
                            theme_manager,
                        )
                        ui.print_info(
                            "Just type your message and press Enter "
                            "to send (no '/send' needed).",
                            theme_manager,
                        )

        elif cmd == "contacts":
            sort_by = "id"
            if args:
                a = args.strip().lower().replace("=", " ").split()
                if "--sort" in a:
                    idx = a.index("--sort")
                    if idx + 1 < len(a):
                        sort_by = a[idx + 1]
                elif a[0] in ("alias", "id"):
                    sort_by = a[0]
                if sort_by not in ("id", "alias"):
                    ui.print_error(
                        "Sort must be 'id' or 'alias'.", theme_manager
                    )
                    sort_by = "id"
            commands.list_contacts(local_db, sort_by=sort_by)

        elif cmd == "import":
            if not args:
                ui.print_error(
                    "Usage: /import <public_key>", theme_manager
                )
            else:
                commands.import_contact(local_db, args.strip())

        elif cmd == "alias":
            if not args:
                ui.print_error(
                    "Usage: /alias <device_id> <new_alias>", theme_manager
                )
            else:
                alias_parts = args.split(maxsplit=1)
                if len(alias_parts) < 2:
                    ui.print_error(
                        "Usage: /alias <device_id> <new_alias>",
                        theme_manager,
                    )
                    ui.print_info(
                        "Use an empty alias string to clear: "
                        "/alias <device_id> \"\"",
                        theme_manager,
                    )
                else:
                    commands.set_alias(
                        local_db, alias_parts[0], alias_parts[1].strip('"')
                    )
                    if active_contact == local_db.resolve_contact(alias_parts[0]):
                        active_contact_display = (
                            local_db.display_name(active_contact)
                            if active_contact else None
                        )

        elif cmd == "theme":
            commands.handle_theme_command(cfg, args)

        elif cmd == "config":
            if not args:
                print()
                print("Configuration")
                for key in ("server_url", "auto_sync", "sync_interval", "theme"):
                    print(f"  {key}: {cfg.get(key)}")
                print()
            else:
                cfg_parts = args.split(maxsplit=1)
                if len(cfg_parts) == 2:
                    commands.set_config(cfg, cfg_parts[0], cfg_parts[1])
                    sync_wake.set()
                else:
                    ui.print_error(
                        "Usage: /config <key> <value>", theme_manager
                    )
                    ui.print_info(
                        "Keys: server_url, auto_sync, sync_interval, theme",
                        theme_manager,
                    )

        elif cmd == "server":
            if not args:
                ui.print_info(
                    f"Server URL: {cfg.server_url}", theme_manager
                )
            else:
                url = args.strip().rstrip("/")
                if not (url.startswith("http://") or url.startswith("https://")):
                    ui.print_error(
                        "URL must start with http:// or https://",
                        theme_manager,
                    )
                else:
                    cfg.set("server_url", url)
                    ui.print_success(
                        f"Server URL set to: {url}", theme_manager
                    )

        elif cmd == "clear":
            os.system("clear" if os.name != "nt" else "cls")
            if theme_manager:
                ui.print_small_banner(theme_manager)
                ui.print_status_bar(
                    active_contact=active_contact_display,
                    auto_sync=cfg.auto_sync,
                    sync_interval=cfg.sync_interval,
                    theme_name=cfg.theme,
                    connected=True,
                    tm=theme_manager,
                )

        elif cmd == "debug":
            commands.show_debug_info(crypto_engine, local_db, cfg)
            if active_contact:
                ui.print_info(
                    f"Active contact: {active_contact_display} ({active_contact})",
                    theme_manager,
                )

        elif cmd == "status":
            ui.print_status_bar(
                active_contact=active_contact_display,
                auto_sync=cfg.auto_sync,
                sync_interval=cfg.sync_interval,
                theme_name=cfg.theme,
                connected=True,
                tm=theme_manager,
            )

        else:
            ui.print_error(f"Unknown command: /{cmd}", theme_manager)
            ui.print_info(
                "Type '/help' for a list of commands.", theme_manager
            )

    except KeyboardInterrupt:
        print("\nCommand interrupted.")
    except Exception as e:
        ui.print_error(f"{e}", theme_manager)
        if os.environ.get("NYX_DEBUG"):
            traceback.print_exc()

    return True