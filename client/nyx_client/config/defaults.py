"""
defaults.py — Default configuration values and path constants for NYX.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

VERSION = "0.0.3"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

NYX_HOME = Path.home() / ".nyx"
CONFIG_PATH = NYX_HOME / "config.json"
LOCAL_DB_PATH = NYX_HOME / "nyx_local.db"

DEFAULT_CONFIG: dict = {
    "server_url": "http://localhost:8000",
    "auto_sync": True,
    "sync_interval": 3,
    "theme": "matrix",
}