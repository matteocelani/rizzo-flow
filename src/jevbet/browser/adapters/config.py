"""Adapter configuration. JSON in, no secrets.

YAML is accepted when PyYAML is installed. The repository does not depend on
it: ship JSON, or convert. Never put usernames, passwords, cookies, or tokens
in the file — not even gitignored ones that might be copied into a fixture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from jevbet.browser.chrome import DEFAULT_LOCAL_PREFIXES, SelectorMap, url_is_allowed

_ALLOWED_KEYS = frozenset(
    {"comment", "name", "game", "base_url", "selectors", "allowed_url_prefixes", "headless"}
)
_SECRET_KEYS = frozenset(
    {
        "password",
        "username",
        "user",
        "token",
        "cookie",
        "cookies",
        "api_key",
        "apikey",
        "secret",
        "credentials",
        "authorization",
    }
)


@dataclass
class AdapterConfig:
    """Where a driver may navigate, which game it is, and which selectors to use.

    ``allowed_url_prefixes`` defaults to loopback. A wider list is an explicit
    choice for an adapter you control.
    """

    game: str
    base_url: str
    selectors: SelectorMap = field(default_factory=SelectorMap)
    allowed_url_prefixes: tuple[str, ...] = DEFAULT_LOCAL_PREFIXES
    headless: bool = True
    name: str = ""

    def __post_init__(self) -> None:
        self.allowed_url_prefixes = tuple(self.allowed_url_prefixes)
        if not self.game or not str(self.game).strip():
            raise ValueError("adapter game is required")
        if not url_is_allowed(self.base_url, self.allowed_url_prefixes):
            raise ValueError(
                f"base_url {self.base_url!r} is outside allowed_url_prefixes "
                f"{list(self.allowed_url_prefixes)}. The default is localhost only."
            )


def load_adapter_config(path: Path | str) -> AdapterConfig:
    """Load a user-owned adapter file. Rejects credential-shaped keys."""
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    suffix = file.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise ImportError(
                "YAML adapter configs need PyYAML, which this project does not depend on. "
                "Use JSON (see examples/mock-casino/adapter.example.json) or install PyYAML "
                "locally. Do not commit secrets."
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("adapter config must be a JSON object")
    lowered = {str(key).lower() for key in data}
    leaked = sorted(lowered & _SECRET_KEYS)
    if leaked:
        raise ValueError(
            f"Adapter config must not contain credentials ({', '.join(leaked)}). "
            "Keep secrets in the browser profile or an environment variable you do not commit."
        )
    unknown = sorted(set(data) - _ALLOWED_KEYS)
    if unknown:
        raise ValueError(f"Unknown adapter config keys: {unknown}")
    selectors_raw = data.get("selectors") or {}
    if not isinstance(selectors_raw, dict):
        raise TypeError("selectors must be an object")
    prefixes = data.get("allowed_url_prefixes", DEFAULT_LOCAL_PREFIXES)
    if isinstance(prefixes, str) or not isinstance(prefixes, (list, tuple)):
        raise TypeError("allowed_url_prefixes must be a list of URL prefixes")
    return AdapterConfig(
        game=str(data["game"]),
        base_url=str(data["base_url"]),
        selectors=SelectorMap(**selectors_raw),
        allowed_url_prefixes=tuple(prefixes),
        headless=bool(data.get("headless", True)),
        name=str(data.get("name") or ""),
    )
