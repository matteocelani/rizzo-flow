"""Browser adapters: mock HTML tables and a Playwright Chromium skeleton."""

from .chrome import ChromeTableDriver, SelectorMap
from .driver import TableDriver
from .mock import FIXTURES_DIR, MockTableDriver

__all__ = [
    "FIXTURES_DIR",
    "ChromeTableDriver",
    "MockTableDriver",
    "SelectorMap",
    "TableDriver",
]
