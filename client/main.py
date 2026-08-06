#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path

from config import load_settings
from db import NYXDatabase
from crypto import Identity
from commands import CommandContext
from ui import ReplUI, NyxTUI


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='NYX - Secure Messaging Client')
    parser.add_argument('--config', help='Config file path')
    parser.add_argument('--repl', action='store_true', help='Use REPL interface')
    parser.add_argument('--tui', action='store_true', help='Use TUI interface (default)')
    args = parser.parse_args()
    
    # Load settings
    settings = load_settings(args.config)
    
    # Initialize database
    db_path = settings.storage.database_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = NYXDatabase(db_path)
    
    # Load or create identity
    identity_data = db.load_identity()
    if identity_data:
        identity = Identity.load(identity_data['private_key'])
        identity_id = identity_data['id']
    else:
        identity = Identity.create()
        identity_id = identity.id
        db.save_identity(identity_id, identity.private_key_bytes, identity.public_key_bytes)
    
    # Get server URL
    server = settings.network.default_server
    
    # Create command context
    ctx = CommandContext(
        identity=identity,
        identity_id=identity_id,
        server=server,
        connected=False,
        db=db
    )
    
    # Determine which UI to use
    use_repl = args.repl
    use_tui = args.tui or not args.repl  # TUI is default
    
    try:
        if use_repl:
            # Use REPL interface
            ui = ReplUI(ctx)
            ui.run()
        else:
            # Use TUI interface
            ui = NyxTUI(ctx)
            ui.run()
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        db.close()


if __name__ == '__main__':
    main()