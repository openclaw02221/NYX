"""
settings.py — Client configuration management for NYX.

Stores server URL, theme, auto-sync settings, and database path.
Config location: ~/.nyx/config.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from nyx_client.config.defaults import (
    CONFIG_PATH,
    DEFAULT_CONFIG,
    LOCAL_DB_PATH,
    NYX_HOME,
    VERSION,
)


class NYXConfig:
    """Manages the local NYX configuration file."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or CONFIG_PATH
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}

    def exists(self) -> bool:
        """Return True if the config file exists on disk."""
        return self.config_path.is_file()

    def load(self) -> dict:
        """Load the config from disk. Returns defaults if missing/corrupt."""
        if not self.exists():
            self._data = dict(DEFAULT_CONFIG)
            return self._data
        try:
            raw = self.config_path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
            # Merge with defaults so new keys appear for older configs
            self._data = dict(DEFAULT_CONFIG)
            self._data.update(loaded)
        except (json.JSONDecodeError, OSError):
            self._data = dict(DEFAULT_CONFIG)
        return self._data

    def save(self) -> None:
        """Persist the current config to disk."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self._data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value."""
        if not self._data:
            self.load()
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a config value and save immediately."""
        if not self._data:
            self.load()
        self._data[key] = value
        self.save()

    def ensure_defaults(self) -> None:
        """Ensure all default keys exist (for partially written configs)."""
        if not self._data:
            self.load()
        changed = False
        for key, value in DEFAULT_CONFIG.items():
            if key not in self._data:
                self._data[key] = value
                changed = True
        if changed:
            self.save()

    # -- convenience properties -----------------------------------------------

    @property
    def server_url(self) -> str:
        return str(self.get("server_url", DEFAULT_CONFIG["server_url"]))

    @property
    def auto_sync(self) -> bool:
        return bool(self.get("auto_sync", DEFAULT_CONFIG["auto_sync"]))

    @property
    def sync_interval(self) -> int:
        try:
            return max(1, int(self.get("sync_interval", DEFAULT_CONFIG["sync_interval"])))
        except (TypeError, ValueError):
            return int(DEFAULT_CONFIG["sync_interval"])

    @property
    def theme(self) -> str:
        return str(self.get("theme", DEFAULT_CONFIG["theme"]))

    @property
    def db_path(self) -> Path:
        env = os.environ.get("NYX_DB_PATH")
        if env:
            return Path(env)
        return LOCAL_DB_PATH