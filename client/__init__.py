"""
NYX Client Package.
"""

try:
    from .ui import ReplUI, NyxTUI
    from .commands import CommandContext, CommandResult, registry
    from .db import NYXDatabase
    from .config import Settings, load_settings
    from .crypto import Identity
except ImportError:
    # Handle cases where we are running from within the client directory
    from ui import ReplUI, NyxTUI
    from commands import CommandContext, CommandResult, registry
    from db import NYXDatabase
    from config import Settings, load_settings
    from crypto import Identity

__all__ = [
    "ReplUI", 
    "NyxTUI", 
    "CommandContext", 
    "CommandResult", 
    "registry", 
    "NYXDatabase", 
    "load_settings",
    "Identity"
]