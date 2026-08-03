"""
NYX Client Configuration Management.

Handles configuration loading from ~/.nyx/config.json with XDG compliance.
Consolidated from config/settings.py, config/defaults.py, config/logging.py.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import structlog


# Configuration defaults
DEFAULT_SERVER = "https://nyx-relay.railway.app"
CONFIG_DIR_NAME = "nyx"
CONFIG_FILE_NAME = "config.json"
DATA_DIR_NAME = "nyx"
DB_FILENAME = "nyx.db"


@dataclass
class NetworkSettings:
    """Network configuration."""
    default_server: str = DEFAULT_SERVER
    connection_timeout: int = 10
    max_retries: int = 3


@dataclass
class StorageSettings:
    """Storage configuration."""
    data_dir: str = ""
    db_filename: str = DB_FILENAME

    def resolved_data_dir(self) -> Path:
        """Return the absolute data directory."""
        if self.data_dir:
            return Path(self.data_dir).expanduser().resolve()
        return default_data_dir()

    def database_path(self) -> Path:
        return self.resolved_data_dir() / self.db_filename


@dataclass
class Settings:
    """Root configuration object."""
    network: NetworkSettings = field(default_factory=NetworkSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    config_path: Path = field(default_factory=lambda: Path())
    data_dir: Path = field(default_factory=lambda: Path())


def default_config_dir() -> Path:
    """XDG_CONFIG_HOME/nyx or ~/.config/nyx."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / CONFIG_DIR_NAME
    return Path.home() / ".config" / CONFIG_DIR_NAME


def default_data_dir() -> Path:
    """XDG_DATA_HOME/nyx or ~/.local/share/nyx."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / DATA_DIR_NAME
    return Path.home() / ".local" / "share" / DATA_DIR_NAME


def default_config_path() -> Path:
    return default_config_dir() / CONFIG_FILE_NAME


def load_settings(config_path: Optional[Path] = None) -> Settings:
    """Load configuration from JSON file."""
    path = config_path or default_config_path()
    
    # Load from file if exists
    config_data: Dict[str, Any] = {}
    if path.exists():
        with open(path, 'r') as f:
            config_data = json.load(f)
    
    # Build settings
    network = NetworkSettings(
        default_server=config_data.get('network', {}).get('default_server', DEFAULT_SERVER),
        connection_timeout=config_data.get('network', {}).get('connection_timeout', 10),
        max_retries=config_data.get('network', {}).get('max_retries', 3),
    )
    
    storage = StorageSettings(
        data_dir=config_data.get('storage', {}).get('data_dir', ''),
        db_filename=config_data.get('storage', {}).get('db_filename', DB_FILENAME),
    )
    
    data_dir = storage.resolved_data_dir()
    
    return Settings(
        network=network,
        storage=storage,
        config_path=path,
        data_dir=data_dir,
    )


def ensure_directories(settings: Settings) -> None:
    """Create config and data directories if they don't exist."""
    config_dir = settings.config_path.parent
    config_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Configure structured logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    
    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
    )


def get_logger(name: str) -> Any:
    """Get a structured logger instance."""
    return structlog.get_logger(name)