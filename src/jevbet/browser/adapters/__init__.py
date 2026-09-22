"""Pluggable table adapters.

The only built-in adapter is the local mock casino. A real-site adapter is a
config file plus, when the DOM is not the mock ``data-*`` contract, a
``ChromeTableDriver`` subclass. See ``docs/jevbet.md``.
"""

from .config import AdapterConfig, load_adapter_config
from .mock_casino import MockCasinoAdapter

__all__ = ["AdapterConfig", "MockCasinoAdapter", "load_adapter_config"]
