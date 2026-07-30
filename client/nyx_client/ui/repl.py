"""
repl.py — Interactive REPL loop for NYX Messenger.

Uses prompt_toolkit with patch_stdout for safe background-sync display.
"""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout

from nyx_client import config
from nyx_client import crypto
from nyx_client import ui
from nyx_client.core import app
from nyx_client.storage import NYXDatabase


def build_prompt() -> str:
    """Build the input prompt, reflecting the active contact if any."""
    if app.active_contact_display:
        return f"nyx({app.active_contact_display})> "
    return "nyx> "


def run_repl(
    cfg: config.NYXConfig,
    local_db: NYXDatabase,
    crypto_engine: crypto.NYXCrypto,
    no_sync: bool = False,
) -> None:
    """
    Main REPL loop using prompt_toolkit with patch_stdout for background sync.

    The patch_stdout() context manager ensures that all print() calls
    (including from the background sync thread) are rendered safely
    without corrupting the prompt_toolkit input line.
    """
    import threading

    history_path = config.NYX_HOME / ".nyx_history"
    config.NYX_HOME.mkdir(parents=True, exist_ok=True)

    prompt_session: PromptSession = PromptSession(
        history=FileHistory(str(history_path)),
    )

    # Start background sync thread unless disabled
    if not no_sync:
        app.sync_thread = threading.Thread(
            target=app.background_sync,
            args=(cfg, local_db, crypto_engine),
            daemon=True,
            name="nyx-sync",
        )
        app.sync_thread.start()

    # Status bar once at start
    ui.print_status_bar(
        active_contact=app.active_contact_display,
        auto_sync=cfg.auto_sync and not no_sync,
        sync_interval=cfg.sync_interval,
        theme_name=cfg.theme,
        connected=True,
        tm=app.theme_manager,
    )
    print()
    if not app.active_contact:
        ui.print_info(
            "Use '/switch <contact>' to start chatting, "
            "or type '/help'.",
            app.theme_manager,
        )
        print()

    with patch_stdout():
        while app.running:
            try:
                # Flush any queued messages before showing the prompt
                app.flush_message_queue()

                line = prompt_session.prompt(build_prompt())
                if not app.process_command(line, cfg, local_db, crypto_engine):
                    break
            except KeyboardInterrupt:
                print()  # move past ^C
                continue
            except EOFError:
                print()
                ui.print_info("Goodbye. Stay encrypted.", app.theme_manager)
                break

    app.running = False
    app.sync_wake.set()
    if app.sync_thread and app.sync_thread.is_alive():
        app.sync_thread.join(timeout=2)