"""
themes.py — Theme definitions for NYX Messenger.

Provides colour palettes applied across the terminal UI via rich styles.
"""

from __future__ import annotations

from typing import Dict, List

# ---------------------------------------------------------------------------
# Theme palettes
# ---------------------------------------------------------------------------

MATRIX_THEME: Dict[str, str] = {
    "name": "matrix",
    "background": "black",
    "foreground": "green",
    "accent": "cyan",
    "error": "bold red",
    "success": "bold green",
    "info": "cyan",
    "warning": "yellow",
    "timestamp": "dim cyan",
    "sender": "bold cyan",
    "message": "white",
    "you": "bold green",
    "prompt": "bold green",
    "banner": "bold green",
    "status": "dim green",
    "border": "green",
    "dim": "dim green",
}

TELEGRAM_THEME: Dict[str, str] = {
    "name": "telegram",
    "background": "black",
    "foreground": "white",
    "accent": "dodger_blue1",
    "error": "bold red",
    "success": "bold green",
    "info": "dodger_blue1",
    "warning": "yellow",
    "timestamp": "dim blue",
    "sender": "bold dodger_blue1",
    "message": "white",
    "you": "bold bright_blue",
    "prompt": "bold dodger_blue1",
    "banner": "bold dodger_blue1",
    "status": "dim blue",
    "border": "dodger_blue1",
    "dim": "dim white",
}

MONOCHROME_THEME: Dict[str, str] = {
    "name": "monochrome",
    "background": "black",
    "foreground": "white",
    "accent": "bright_white",
    "error": "bold white",
    "success": "bold white",
    "info": "white",
    "warning": "white",
    "timestamp": "dim white",
    "sender": "bold white",
    "message": "white",
    "you": "bold bright_white",
    "prompt": "bold white",
    "banner": "bold white",
    "status": "dim white",
    "border": "white",
    "dim": "dim white",
}

SOLARIZED_THEME: Dict[str, str] = {
    "name": "solarized",
    "background": "black",
    "accent": "cyan",
    "foreground": "#839496",
    "error": "bold red",
    "success": "bold green",
    "info": "cyan",
    "warning": "yellow",
    "timestamp": "dim cyan",
    "sender": "bold yellow",
    "message": "#93a1a1",
    "you": "bold green",
    "prompt": "bold cyan",
    "banner": "bold yellow",
    "status": "dim cyan",
    "border": "cyan",
    "dim": "dim #586e75",
}

# Registry of all available themes
THEMES: Dict[str, Dict[str, str]] = {
    "matrix": MATRIX_THEME,
    "telegram": TELEGRAM_THEME,
    "monochrome": MONOCHROME_THEME,
    "solarized": SOLARIZED_THEME,
}

DEFAULT_THEME = "matrix"

# Palette used to colour-code different senders
SENDER_COLORS: List[str] = [
    "cyan",
    "magenta",
    "yellow",
    "bright_blue",
    "bright_green",
    "bright_magenta",
    "bright_cyan",
    "bright_yellow",
    "orange1",
    "spring_green1",
    "deep_pink1",
    "turquoise2",
]


class ThemeManager:
    """Manages the active theme and provides style lookups."""

    def __init__(self, theme_name: str = DEFAULT_THEME):
        self._name = theme_name if theme_name in THEMES else DEFAULT_THEME
        self._theme = THEMES[self._name]
        self._sender_color_map: Dict[str, str] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def theme(self) -> Dict[str, str]:
        return self._theme

    def set_theme(self, name: str) -> bool:
        """Switch to a named theme. Returns True on success."""
        key = name.lower().strip()
        if key not in THEMES:
            return False
        self._name = key
        self._theme = THEMES[key]
        return True

    def get(self, key: str, default: str = "white") -> str:
        """Return a style string for the given semantic key."""
        return self._theme.get(key, default)

    def style(self, key: str) -> str:
        """Alias for get()."""
        return self.get(key)

    def sender_color(self, sender_id: str) -> str:
        """
        Return a stable colour for a given sender device_id / alias.
        The same sender always gets the same colour within a session.
        """
        if sender_id not in self._sender_color_map:
            idx = abs(hash(sender_id)) % len(SENDER_COLORS)
            self._sender_color_map[sender_id] = SENDER_COLORS[idx]
        return self._sender_color_map[sender_id]

    @staticmethod
    def list_themes() -> List[str]:
        """Return sorted list of available theme names."""
        return sorted(THEMES.keys())