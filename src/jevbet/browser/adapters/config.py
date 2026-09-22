"""Adapter configuration. JSON in, no secrets.

YAML is accepted when PyYAML is installed. The repository does not depend on
it: ship JSON, or convert. Never put usernames, passwords, cookies, or tokens
in the file — not even gitignored ones that might be copied into a fixture.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from jevbet.browser.chrome import DEFAULT_LOCAL_PREFIXES, SelectorMap, url_is_allowed

_ALLOWED_KEYS = frozenset(
    {"comment", "name", "game", "base_url", "selectors", "allowed_url_prefixes", "headless"}
)
# Segment names after camelCase / separator normalization. Plurals are handled
# by stripping a trailing "s". ``api`` + ``key`` is matched as a pair so
# ``api_key`` / ``apiKey`` / ``API-KEY`` all hit.
_CREDENTIAL_SEGMENTS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "cookie",
        "authorization",
        "credential",
        "username",
        "user",
        "apikey",
    }
)
# Substrings inside one segment (``passwordHash``, ``clientsecret``). ``token``
# and ``user`` stay exact so words like ``tokenize`` are left alone.
_CREDENTIAL_SUBSTRINGS = (
    "password",
    "passwd",
    "secret",
    "apikey",
    "authorization",
    "credential",
    "cookie",
    "username",
)
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_ACRONYM_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


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


def _normalize_key(key: object) -> str:
    """Lowercase snake form: ``apiKey`` and ``API-KEY`` both become ``api_key``."""
    text = _CAMEL_BOUNDARY.sub(r"\1_\2", str(key))
    text = _ACRONYM_BOUNDARY.sub(r"\1_\2", text)
    text = _NON_ALNUM.sub("_", text)
    return text.strip("_").lower()


def _is_credential_key(key: object) -> bool:
    """True when ``key`` looks like a password, token, cookie, or similar secret."""
    normalized = _normalize_key(key)
    if not normalized:
        return False
    parts = normalized.split("_")
    for index, part in enumerate(parts):
        singular = part.removesuffix("s")
        if part in _CREDENTIAL_SEGMENTS or singular in _CREDENTIAL_SEGMENTS:
            return True
        if any(word in part for word in _CREDENTIAL_SUBSTRINGS):
            return True
        if part == "api" and index + 1 < len(parts) and parts[index + 1].removesuffix("s") == "key":
            return True
    return False


def _credential_paths(value: object, prefix: str = "") -> list[str]:
    """Paths of credential-shaped keys in nested dicts and lists."""
    found: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            name = str(raw_key)
            path = f"{prefix}.{name}" if prefix else name
            if _is_credential_key(raw_key):
                found.append(path)
            found.extend(_credential_paths(child, path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.extend(_credential_paths(child, f"{prefix}[{index}]"))
    return found


def load_adapter_config(path: Path | str) -> AdapterConfig:
    """Load a user-owned adapter file.

    Credential-shaped keys are rejected anywhere in the document, not only at
    the top level (``selectors.extra.password``, a nested ``api_key``, and so
    on). Matching is case-insensitive.
    """
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
    leaked = sorted(set(_credential_paths(data)))
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
