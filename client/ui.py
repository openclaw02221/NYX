"""
ui.py — Compatibility shim.

This file re-exports everything from nyx_client.ui.display for backward compatibility.
New code should import directly from nyx_client.ui or nyx_client.ui.display.
"""
from nyx_client.ui.display import (  # noqa: F401
    ANSI,
    ColorSystem,
    Console,
    Spinner,
    ThemeManager,
    display_chat_message,
    display_contacts,
    hide_spinner,
    input_yes_no,
    no_color_mode,
    print_banner,
    print_status,
    show_spinner,
    show_sync_spinner,
    test_connection_with_spinner,
)