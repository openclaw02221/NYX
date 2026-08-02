"""
NYX Client — Textual TUI / REPL entry point.
"""

import sys
import argparse
from commands import CommandContext, registry
from config import load_settings, configure_logging, get_logger
from db import NYXDatabase
from crypto import Identity
from ui import ReplUI, NyxTUI


def main() -> int:
    parser = argparse.ArgumentParser(
        description="NYX — Terminal-Native Secure Messaging Client"
    )
    parser.add_argument("--repl", action="store_true", help="use REPL UI")
    parser.add_argument("--tui", action="store_true", help="use Textual TUI")
    args = parser.parse_args()

    # Load settings
    settings = load_settings()
    configure_logging(level="INFO", json_logs=False)
    log = get_logger(__name__)

    # Initialize database
    db_path = settings.storage.database_path()
    db = NYXDatabase(db_path)
    db.connect()

    # Load or create identity
    identity_data = db.load_identity()
    if identity_data:
        identity_id = identity_data.get("identity_id", "unknown")
        identity = Identity.create()  # placeholder until full key restoration
    else:
        identity = Identity.create()
        identity_id = identity.id
        db.save_identity(identity_id, identity.public_key_bytes, b"placeholder")

    log.info("identity", id=identity_id)

    # Build command context
    ctx = CommandContext(
        identity=identity,
        identity_id=identity_id,
        server=settings.network.default_server,
        connected=False,
        db=db,
    )

    # Launch chosen UI
    if args.repl:
        ui = ReplUI(ctx)
        return ui.run()
    else:
        # TUI (default when neither --repl nor --tui is specified)
        app = NyxTUI(ctx=ctx)
        app.run()
        return 0


if __name__ == "__main__":
    sys.exit(main())