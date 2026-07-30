"""
main.py — NYX Messenger interactive REPL entry point.

Features:
  • First-run wizard (server URL, identity, registration)
  • prompt_toolkit line editing with history
  • Background auto-sync thread (configurable interval)
  • Smart input parsing: commands start with '/', bare text → send to active contact
  • Irssi/WeeChat-style active-contact chat with status bar
  • Thread-safe message display via queue + prompt_toolkit
  • Contact aliases and theme system
  • Session-only message display (no plaintext persistence)

Usage:
    python main.py               # Start the REPL
    python main.py --server URL  # Override the server URL
    python main.py --no-sync     # Disable background auto-sync
"""

from __future__ import annotations

import argparse
import sys

from nyx_client import config
from nyx_client import crypto
from nyx_client import ui
from nyx_client.core import app, commands
from nyx_client.storage import NYXDatabase
from nyx_client.ui.repl import run_repl
from nyx_client.themes import ThemeManager


def main() -> None:
    """Entry point for the NYX Messenger REPL."""
    parser = argparse.ArgumentParser(
        description="NYX Messenger — End-to-end encrypted messaging client",
    )
    parser.add_argument(
        "--server", "-s",
        help="Server URL (overrides config / wizard)",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Disable background auto-sync",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable coloured output",
    )
    args = parser.parse_args()

    # ── Colour mode ────────────────────────────────────────────────
    # ui already defaults to no_color=True, plain text output.
    # This avoids raw ANSI codes showing as text on Arch Linux terminals.
    # If --no-color is explicitly passed, keep the already-set no_color mode.

    # ── Initialize configuration ───────────────────────────────────
    cfg = config.NYXConfig()
    first_run = not cfg.exists()
    cfg.load()
    cfg.ensure_defaults()

    if args.server:
        url = args.server.strip().rstrip("/")
        cfg.set("server_url", url)

    # ── Theme ──────────────────────────────────────────────────────
    app.theme_manager = ThemeManager(cfg.theme)
    commands.set_theme_manager(app.theme_manager)

    # ── Initialize database ────────────────────────────────────────
    local_db = NYXDatabase(cfg.db_path)

    # ── Initialize cryptographic identity ──────────────────────────
    crypto_engine = crypto.NYXCrypto(
        device_id_path=str(config.NYX_HOME / "device_id"),
        keys_path=str(config.NYX_HOME / "keys"),
    )

    # ── First-run wizard ───────────────────────────────────────────
    if first_run and not args.server:
        ok = ui.run_first_run_wizard(
            cfg,
            local_db,
            crypto_engine,
            register_fn=lambda c, d, e: commands.register(c, d, e, quiet=True),
            tm=app.theme_manager,
        )
        if not ok:
            sys.exit(1)
        # Reload theme in case wizard set it
        app.theme_manager.set_theme(cfg.theme)
    else:
        # Returning user — show compact banner
        ui.print_small_banner(app.theme_manager)

        # Ensure identity exists
        if not crypto_engine.has_identity():
            ui.print_info("No local identity found. Generating...", app.theme_manager)
            crypto_engine.generate_identity()

        # Auto-register if needed
        if not local_db.is_registered():
            ui.print_info("Registering with server...", app.theme_manager)
            commands.register(cfg, local_db, crypto_engine)

        # Connection status line
        ui.print_info(f"Server: {cfg.server_url}", app.theme_manager)
        if crypto_engine.device_id:
            ui.print_info(
                f"Identity: {crypto_engine.device_id}", app.theme_manager
            )
        print()

    # ── Run the REPL ───────────────────────────────────────────────
    try:
        run_repl(cfg, local_db, crypto_engine, no_sync=args.no_sync)
    finally:
        local_db.close()


if __name__ == "__main__":
    main()