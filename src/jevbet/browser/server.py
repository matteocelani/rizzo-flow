"""Loopback HTTP server for the mock-casino fixtures.

Binds to 127.0.0.1 only. CI and ``jevbet play --browser`` use this instead of
opening the HTML via ``file://``.
"""

from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode

from .mock import FIXTURES_DIR

_PAGES = frozenset({"blackjack.html", "holdem.html", "casino.js", "casino.css"})


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def list_directory(self, path):
        self.send_error(404, "No directory listing")


class MockCasinoServer:
    """Serve ``src/jevbet/browser/fixtures`` on an ephemeral loopback port."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("Mock casino HTTP server binds to loopback only")
        self.host = "127.0.0.1" if host == "localhost" else host
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> MockCasinoServer:
        if self._httpd is not None:
            return self
        directory = str(FIXTURES_DIR.resolve())

        def handler(*args, **kwargs):
            return _QuietHandler(*args, directory=directory, **kwargs)

        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="jevbet-mock-casino",
            daemon=True,
        )
        self._thread.start()
        return self

    def url_for(self, page: str, query: dict[str, str] | None = None) -> str:
        if page not in _PAGES or "/" in page or ".." in page:
            raise ValueError(f"Unknown mock-casino page {page!r}")
        if self._httpd is None:
            raise RuntimeError("Call start() before url_for()")
        url = f"http://127.0.0.1:{self.port}/{page}"
        if query:
            cleaned = {key: value for key, value in query.items() if value is not None}
            if cleaned:
                url += "?" + urlencode(cleaned)
        return url

    def close(self) -> None:
        httpd = self._httpd
        thread = self._thread
        self._httpd = None
        self._thread = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=2)
