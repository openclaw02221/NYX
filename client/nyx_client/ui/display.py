"""
display.py — UI components, ASCII art, First Run Wizard, and display helpers
for NYX Messenger.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from prompt_toolkit import prompt as pt_prompt
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner

# themes.py lives at the client root (on sys.path when running from client/)
from nyx_client.themes import ThemeManager, DEFAULT_THEME

if TYPE_CHECKING:
    from nyx_client.config.settings import NYXConfig
    from nyx_client.crypto.identity import NYXCrypto
    from nyx_client.storage import NYXDatabase

# ---------------------------------------------------------------------------
# Shared console (colour-enabled; theme styles applied per-call)
# ---------------------------------------------------------------------------

console = Console(no_color=True, color_system=None, force_terminal=False)

# ---------------------------------------------------------------------------
# ASCII Art
# ---------------------------------------------------------------------------

NYX_BANNER = r"""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   ███╗   ██╗██╗   ██╗██╗  ██╗                            ║
║   ████╗  ██║╚██╗ ██╔╝╚██╗██╔╝                            ║
║   ██╔██╗ ██║ ╚████╔╝  ╚███╔╝                             ║
║   ██║╚██╗██║  ╚██╔╝   ██╔██╗                             ║
║   ██║ ╚████║   ██║   ██╔╝ ██╗                            ║
║   ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝                            ║
║                                                           ║
║              End-to-End Encrypted Messaging               ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
"""

NYX_BANNER_SMALL = r"""
  ███╗   ██╗██╗   ██╗██╗  ██╗
  ████╗  ██║╚██╗ ██╔╝╚██╗██╔╝
  ██╔██╗ ██║ ╚████╔╝  ╚███╔╝
  ██║╚██╗██║  ╚██╔╝   ██╔██╗
  ██║ ╚████║   ██║   ██╔╝ ██╗
  ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝
"""

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# ---------------------------------------------------------------------------
# Status indicators
# ---------------------------------------------------------------------------

STATUS_CONNECTED = "[✓] Connected"
STATUS_DISCONNECTED = "[✗] Disconnected"
STATUS_SYNCING = "[⟳] Syncing"


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_banner(tm: Optional[ThemeManager] = None) -> None:
    """Print the full NYX welcome banner."""
    print(NYX_BANNER)


def print_small_banner(tm: Optional[ThemeManager] = None) -> None:
    """Print a compact banner for the main session."""
    print(NYX_BANNER_SMALL)
    print("  NYX Messenger v0.0.3")
    print()


def print_status(connected: bool, tm: Optional[ThemeManager] = None) -> None:
    """Print connection status indicator."""
    if connected:
        print(STATUS_CONNECTED)
    else:
        print(STATUS_DISCONNECTED)


def print_error(msg: str, tm: Optional[ThemeManager] = None) -> None:
    """Print a themed error message."""
    print(f"✗ {msg}")


def print_success(msg: str, tm: Optional[ThemeManager] = None) -> None:
    """Print a themed success message."""
    print(f"✓ {msg}")


def print_info(msg: str, tm: Optional[ThemeManager] = None) -> None:
    """Print a themed info message."""
    print(f"· {msg}")


def print_warning(msg: str, tm: Optional[ThemeManager] = None) -> None:
    """Print a themed warning message."""
    print(f"! {msg}")


def message_separator(label: str, tm: Optional[ThemeManager] = None) -> None:
    """Print a horizontal separator with a label."""
    width = 60
    pad = max(0, (width - len(label) - 2) // 2)
    line = "─" * pad + f" {label} " + "─" * pad
    print(line)


def format_timestamp(dt: Optional[datetime] = None) -> str:
    """Return HH:MM:SS timestamp string."""
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%H:%M:%S")


def format_chat_message(
    timestamp: str,
    sender: str,
    content: str,
    is_you: bool = False,
    tm: Optional[ThemeManager] = None,
) -> str:
    """
    Build a plain text chat message line.
    """
    parts = [f"[{timestamp}] "]
    if is_you:
        parts.append("You: ")
    else:
        parts.append(f"{sender}: ")
    parts.append(content)
    return "".join(parts)


def print_chat_message(
    timestamp: str,
    sender: str,
    content: str,
    is_you: bool = False,
    tm: Optional[ThemeManager] = None,
) -> None:
    """Print a formatted chat message to the console."""
    msg = format_chat_message(timestamp, sender, content, is_you=is_you, tm=tm)
    print(msg)


def play_beep() -> None:
    """Play a short terminal bell / beep."""
    try:
        print("\a", end="", flush=True)
    except Exception:
        try:
            import os
            os.system('printf "\\a"')
        except Exception:
            pass


def show_desktop_notification(title: str, message: str) -> None:
    """Show a desktop notification if plyer is available."""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="NYX Messenger",
            timeout=5,
        )
    except Exception:
        pass  # plyer not installed or platform unsupported — silently skip


def notify_new_message(
    sender: str,
    content: str,
    tm: Optional[ThemeManager] = None,
) -> None:
    """
    Fire all three notification channels for an incoming message:
      1. Visual  — already printed by caller
      2. Audio   — terminal beep
      3. Desktop — system notification (if available)
    """
    play_beep()
    preview = content if len(content) <= 80 else content[:77] + "..."
    show_desktop_notification(f"NYX — {sender}", preview)


# ---------------------------------------------------------------------------
# Contacts table
# ---------------------------------------------------------------------------

def print_contacts_table(
    contacts: List[Tuple[str, str, Optional[str]]],
    sort_by: str = "id",
    tm: Optional[ThemeManager] = None,
) -> None:
    """Display all known contacts with aliases using plain text alignment."""
    if not contacts:
        print_info("No contacts yet. Use 'sync' or 'import' to add contacts.", tm)
        return

    if sort_by == "alias":
        contacts = sorted(contacts, key=lambda c: (c[2] or "").lower())
    else:
        contacts = sorted(contacts, key=lambda c: c[0])

    print("=== Known Contacts ===")
    print("Device ID              Alias              Public Key")
    print("---------------------  -----------------  ---------------------")
    for device_id, public_key, alias in contacts:
        alias_display = alias if alias else "—"
        key_display = public_key[:20] + "..." if len(public_key) > 20 else public_key
        print(f"{device_id:<20} {alias_display:<20} {key_display}")
    print()


# ---------------------------------------------------------------------------
# Spinner / connection test
# ---------------------------------------------------------------------------

def _validate_url(url: str) -> Tuple[bool, str]:
    """
    Validate that *url* looks like a proper HTTP(S) URL.
    Returns (ok, error_message).
    """
    url = url.strip()
    if not url:
        return False, "URL cannot be empty."
    if not url.startswith("http://") and not url.startswith("https://"):
        return False, "URL must start with http:// or https://"
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return False, "URL is missing a host (e.g. https://example.com)."
    except Exception:
        return False, "Invalid URL format."
    return True, ""


def test_server_connection(url: str, timeout: int = 8) -> Tuple[bool, str]:
    """
    GET the server health endpoint and return (success, detail_message).
    Shows a spinning indicator while waiting.
    """
    # Normalise: strip trailing slash
    base = url.rstrip("/")
    # Try root health check
    endpoints = [f"{base}/", f"{base}/index.php"]

    last_error = "Unknown error"
    for endpoint in endpoints:
        try:
            # Animated spinner via rich Live
            spinner = Spinner("dots", text=f" Connecting to {base}...", style="cyan")
            with Live(spinner, console=console, refresh_per_second=12, transient=True):
                resp = requests.get(endpoint, timeout=timeout)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    status = data.get("status", "ok")
                    service = data.get("service", "NYX")
                    return True, f"Connected to {service} (status: {status})"
                except Exception:
                    # Non-JSON 200 is still a reachable server
                    return True, f"Server reachable at {base} (HTTP 200)"
            else:
                last_error = f"HTTP {resp.status_code} from {endpoint}"
        except requests.exceptions.ConnectionError:
            last_error = f"Cannot connect to {base} — connection refused"
        except requests.exceptions.Timeout:
            last_error = f"Connection to {base} timed out after {timeout}s"
        except requests.exceptions.SSLError as e:
            last_error = f"SSL error: {e}"
        except Exception as e:
            last_error = f"Error: {e}"

    return False, last_error


def spin_while(message: str, func: Callable, *args, **kwargs):
    """
    Run *func(*args, **kwargs)* while showing a spinner with *message*.
    Returns whatever func returns.
    """
    spinner = Spinner("dots", text=f" {message}", style="cyan")
    with Live(spinner, console=console, refresh_per_second=12, transient=True):
        result = func(*args, **kwargs)
    return result


# ---------------------------------------------------------------------------
# First Run Wizard
# ---------------------------------------------------------------------------

def run_first_run_wizard(
    cfg: "NYXConfig",
    local_db: "NYXDatabase",
    crypto_engine: "NYXCrypto",
    register_fn: Callable,
    tm: Optional[ThemeManager] = None,
) -> bool:
    """
    Interactive first-run setup wizard.

    Steps:
      1. Welcome banner
      2. Prompt for server URL (with validation + connection test)
      3. Generate cryptographic identity
      4. Register with server
      5. Display success with device ID

    Returns True on success, False if the user aborts.
    """
    if tm is None:
        tm = ThemeManager(DEFAULT_THEME)

    print_banner(tm)
    print()
    print("  Welcome to NYX Messenger!")
    print("  This appears to be your first run. Let's get you set up.")
    print()

    # ── Step 1: Server URL ────────────────────────────────────────────
    print(
        "Enter the full URL of your NYX relay server.\n"
        "Example: https://nyx-relay.up.railway.app\n"
        "         http://localhost:8000"
    )
    print()

    server_url: Optional[str] = None
    while server_url is None:
        try:
            raw = pt_prompt("Server URL: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            print_error("Setup cancelled.", tm)
            return False

        if not raw:
            print_error("Please enter a server URL.", tm)
            continue

        ok, err = _validate_url(raw)
        if not ok:
            print_error(err, tm)
            continue

        # Normalise trailing slash
        candidate = raw.rstrip("/")

        print_info(f"Testing connection to {candidate} ...", tm)
        success, detail = test_server_connection(candidate)

        if success:
            print_success(detail, tm)
            server_url = candidate
        else:
            print_error(f"Connection failed: {detail}", tm)
            print(
                "  Please check the URL and try again.",
            )
            print()

    # Save server URL to config
    cfg.set("server_url", server_url)
    # Ensure defaults for new keys
    if cfg.get("auto_sync") is None:
        cfg.set("auto_sync", True)
    if cfg.get("sync_interval") is None:
        cfg.set("sync_interval", 3)
    if cfg.get("theme") is None:
        cfg.set("theme", DEFAULT_THEME)

    print()

    # ── Step 2: Generate identity ─────────────────────────────────────
    print(
        "Generating your cryptographic identity...\n"
        "Ed25519 (identity) + X25519 (encryption)"
    )

    if not crypto_engine.has_identity():
        def _gen():
            crypto_engine.generate_identity()
            time.sleep(0.3)  # brief pause so spinner is visible
        spin_while("Generating keys...", _gen)
        print_success("Cryptographic identity generated.", tm)
    else:
        print_info("Existing identity found — reusing it.", tm)

    device_id = crypto_engine.device_id
    public_key = crypto_engine.get_public_key_b64()
    print(f"  Device ID:  {device_id}")
    print(f"  Public Key: {public_key[:40]}...")
    print()

    # ── Step 3: Register with server ──────────────────────────────────
    print(
        f"Registering device {device_id} with the relay server..."
    )

    def _register():
        return register_fn(cfg, local_db, crypto_engine)

    result = spin_while("Registering with server...", _register)

    if result is None or (isinstance(result, dict) and result.get("status") != "ok"):
        # Registration may have printed its own error; give a summary
        print_warning(
            "Registration may have failed. You can retry later with 'register'.",
            tm,
        )
    else:
        print_success("Registered successfully with the relay server.", tm)

    print()

    # ── Step 4: Success ───────────────────────────────────────────────
    print(
        f"Setup complete!\n\n"
        f"  Device ID:  {device_id}\n"
        f"  Server:     {server_url}\n\n"
        f"Share your public key (via myid) with contacts\n"
        f"so they can send you encrypted messages.\n\n"
        f"Type help for available commands."
    )
    print()
    return True


# ---------------------------------------------------------------------------
# Status bar helper
# ---------------------------------------------------------------------------

def format_status_bar(
    active_contact: Optional[str] = None,
    auto_sync: bool = True,
    sync_interval: int = 3,
    theme_name: str = "matrix",
    connected: bool = True,
) -> str:
    """Build a one-line status bar string for the footer / prompt area."""
    parts = []
    if connected:
        parts.append("✓ Connected")
    else:
        parts.append("✗ Disconnected")

    if active_contact:
        parts.append(f"Active: {active_contact}")
    else:
        parts.append("Active: (none)")

    sync_label = f"Sync: {'ON' if auto_sync else 'OFF'}"
    if auto_sync:
        sync_label += f"/{sync_interval}s"
    parts.append(sync_label)

    parts.append(f"Theme: {theme_name}")
    return " │ ".join(parts)


def print_status_bar(
    active_contact: Optional[str] = None,
    auto_sync: bool = True,
    sync_interval: int = 3,
    theme_name: str = "matrix",
    connected: bool = True,
    tm: Optional[ThemeManager] = None,
) -> None:
    """Print the status bar."""
    bar = format_status_bar(
        active_contact=active_contact,
        auto_sync=auto_sync,
        sync_interval=sync_interval,
        theme_name=theme_name,
        connected=connected,
    )
    print(f"  {bar}")