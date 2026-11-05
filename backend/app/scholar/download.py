"""Fetch a cited paper's PDF from the open web, safely (task 2.3).

The URLs come from third-party metadata (Semantic Scholar's open-access links),
and this runs on a public server, so every download is treated as untrusted:

- **http(s) only, and never an internal address.** A link pointing at
  ``localhost`` or a cloud metadata address would otherwise make the server
  fetch from inside its own network (SSRF). Redirects are followed by hand so
  every hop is checked, not just the first.
- **A size cap**, enforced while streaming, so a huge or endless response
  cannot exhaust memory.
- **It must actually be a PDF.** Publishers commonly answer a "PDF" link with
  an HTML landing page or login wall; the ``%PDF-`` signature is checked
  rather than the Content-Type, which is often wrong.
- **Polite pacing per host.** arXiv asks automated clients for at most one
  request every three seconds.

Known limitation: the address check resolves the host before the request, and
the request resolves it again, so a hostile DNS server could answer differently
the second time (DNS rebinding). Pinning the connection to the checked address
would close it; at this project's scale, checking every hop is the
proportionate step.

What happens to the PDF afterwards is the parser's and the renderer's concern;
the renderer is the patched pdf.js chosen in 1.3 for exactly this step.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
import time
from urllib.parse import urljoin, urlparse

import requests

#: Same ceiling as uploads (reader API).
MAX_BYTES = 50 * 1024 * 1024
TIMEOUT_SECONDS = 30
MAX_REDIRECTS = 4
USER_AGENT = (
    "AURA-Citation-Navigator/0.1 "
    "(+https://github.com/nNilakshii/Agentic-AI-Citation-Navigator)"
)

#: Minimum seconds between requests to one host. arXiv states its limit for
#: automated access; everyone else gets a courteous default.
HOST_INTERVAL = {"arxiv.org": 3.0, "export.arxiv.org": 3.0}
DEFAULT_INTERVAL = 1.0


class DownloadError(RuntimeError):
    """The PDF could not be fetched; ``reason`` says why, in plain words."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _HostPacer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        interval = HOST_INTERVAL.get(host, DEFAULT_INTERVAL)
        with self._lock:
            delay = self._last.get(host, 0.0) + interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last[host] = time.monotonic()


_PACER = _HostPacer()


def check_url(url: str) -> str:
    """Return the host if ``url`` is safe to fetch; raise otherwise."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise DownloadError(f"not an http(s) URL: {url[:80]}")
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise DownloadError(f"cannot resolve {host}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise DownloadError(f"{host} resolves to a non-public address")
    return host


class Downloader:
    """Fetches PDFs. Injectable, so tests never touch the network."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def fetch_pdf(self, url: str) -> bytes:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host = check_url(current)
            _PACER.wait(host)
            try:
                response = self._session.get(
                    current,
                    stream=True,
                    allow_redirects=False,
                    timeout=TIMEOUT_SECONDS,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"},
                )
            except requests.RequestException as exc:
                raise DownloadError(
                    f"request failed: {exc.__class__.__name__}"
                ) from exc

            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise DownloadError("redirect without a location")
                current = urljoin(current, location)
                continue
            if response.status_code != 200:
                response.close()
                raise DownloadError(f"HTTP {response.status_code}")
            return _read_pdf(response)
        raise DownloadError("too many redirects")


def _read_pdf(response) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        response.close()
        raise DownloadError("larger than the 50 MB limit")
    chunks, size = [], 0
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            size += len(chunk)
            if size > MAX_BYTES:
                raise DownloadError("larger than the 50 MB limit")
            chunks.append(chunk)
    finally:
        response.close()
    data = b"".join(chunks)
    if not data.lstrip()[:5] == b"%PDF-":
        # Usually a publisher's HTML landing or login page behind a "PDF" link.
        raise DownloadError("the link did not return a PDF")
    return data


def get_downloader() -> Downloader:
    """Injectable factory — FastAPI overrides this in tests."""
    return Downloader()
