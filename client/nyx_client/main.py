"""
NYX Client entry point.

Whitepaper sections 56 / 47: Python client architecture.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nyx_client import __version__, __whitepaper_version__
from nyx_client.config import configure_logging, get_logger, load_settings
from nyx_client.core.app import NyxApp
from nyx_client.core.backend import TUIBackend
from nyx_client.ui.repl import ReplUI
from nyx_client.ui.tui import NYXApp as TUIApp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nyx", description="NYX Client")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--repl", action="store_true", help="interactive REPL")
    parser.add_argument("--tui", action="store_true", help="curses terminal UI")
    parser.add_argument(
        "--profile-key-file",
        type=Path,
        default=None,
        help="32-byte profile key file (dev)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="override data directory",
    )
    args = parser.parse_args(argv)

    if args.version:
        print("nyx-client " + __version__ + " (whitepaper " + __whitepaper_version__ + ")")
        return 0

    configure_logging(level="INFO", json_logs=False)

    try:
        settings = load_settings()
    except (ValueError, OSError) as exc:
        print("error: configuration: " + str(exc), file=sys.stderr)
        return 1

    if args.data_dir is not None:
        # Rebuild storage section with override via a simple approach:
        from dataclasses import replace
        from nyx_client.config.settings import StorageSettings
        settings = replace(
            settings,
            storage=StorageSettings(
                data_dir=str(args.data_dir),
                db_filename=settings.storage.db_filename,
            ),
            data_dir=args.data_dir.resolve(),
        )

    profile_key = None
    if args.profile_key_file is not None:
        profile_key = args.profile_key_file.read_bytes()

    try:
        app = NyxApp.from_settings(settings=settings, profile_key=profile_key)
        identity = app.start()
    except Exception as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 1

    if app.last_mnemonic:
        print()
        print("  *** NEW IDENTITY CREATED ***")
        print("  " + identity.id)
        print()
        print("  Recovery mnemonic (store offline, never share):")
        print("  " + app.last_mnemonic)
        print()

    # Default to TUI if no mode specified
    if args.repl:
        ui = ReplUI(app.command_context())
        code = ui.run()
        app.stop()
        return code
    
    # Launch TUI (default or --tui flag)
    try:
        backend = TUIBackend(app)
        tui_app = TUIApp(nyx_app=backend)
        tui_app.run()
        app.stop()
        return 0
    except Exception as exc:
        print("error: TUI failed: " + str(exc), file=sys.stderr)
        app.stop()
        return 1


if __name__ == "__main__":
    sys.exit(main())
