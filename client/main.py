"""
NYX Client — Textual TUI / REPL entry point.
"""

import sys
import argparse
import asyncio
from commands import CommandContext, registry
from config import load_settings, configure_logging, ensure_directories, get_logger
from db import NYXDatabase
from crypto import Identity
from ui import ReplUI, NyxTUI


async def main_async() -> int:
    parser = argparse.ArgumentParser(
        description="NYX — Terminal-Native Secure Messaging Client"
    )
    parser.add_argument("--repl", action="store_true", help="use REPL UI")
    parser.add_argument("--tui", action="store_true", help="use Textual TUI")
    args = parser.parse_args()

    # Load settings
    settings = load_settings()
    ensure_directories(settings)
    configure_logging(level="INFO", json_logs=False)
    log = get_logger(__name__)

    # Initialize database
    db_path = settings.storage.database_path()
    db = NYXDatabase(db_path)
    db.connect()

    # Load or create identity
    identity_data = db.load_identity()
    if identity_data:
        identity_id = identity_data["identity_id"]
        # Use saved private key to restore identity
        identity = Identity.from_private_bytes(identity_data["enc_identity_key"])
        connected = True
    else:
        identity = Identity.create()
        identity_id = identity.id
        db.save_identity(identity_id, identity.public_key_bytes, identity.identity_key.private_bytes())
        connected = False

    log.info("identity", id=identity_id)

    # Build command context
    ctx = CommandContext(
        identity=identity,
        identity_id=identity_id,
        server=settings.network.default_server,
        connected=connected,
        db=db,
    )

    # Launch chosen UI
    if args.repl:
        ui = ReplUI(ctx, registry)
        return ui.run()
    else:
        # TUI (default when neither --repl nor --tui is specified)
        app = NyxTUI(ctx)
        await app.run_async()
        return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--repl":
        # REPL mode is synchronous
        sys.exit(asyncio.run(main_async()))
    else:
        # TUI mode needs to run without nested event loop
        asyncio.run(main_async())


if __name__ == "__main__":
    main()