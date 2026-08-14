from __future__ import annotations

import ipaddress
import re
import socket
import ssl
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from agent_service.certs import ssl_context

BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.google.com",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._chunks: list[str] = []
        self.title = ""
        self.description = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            names = {k: (v or "") for k, v in attrs}
            key = names.get("name") or names.get("property")
            if key in {"description", "og:description"} and names.get("content") and not self.description:
                self.description = names["content"]

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
        self._chunks.append(text)

    def text(self) -> str:
        joined = " ".join(self._chunks)
        body = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", joined)).strip()
        parts = [part for part in (self.title, self.description, body) if part]
        seen: list[str] = []
        for part in parts:
            if part not in seen:
                seen.append(part)
        return "\n\n".join(seen)


def looks_like_url(text: str) -> str | None:
    stripped = text.strip()
    match = re.search(r"https?://[^\s<>\"']+", stripped)
    if match:
        return match.group(0).rstrip(").,，。]」』")
    match = re.search(r"(?:www\.)[^\s<>\"']+\.[a-zA-Z]{2,}[^\s<>\"']*", stripped)
    if match:
        return "https://" + match.group(0).rstrip(").,，。]」』")
    return None


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or (ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


def assert_public_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("RT.CAPTURE.SSRF")
    if parsed.username or parsed.password:
        raise ValueError("RT.CAPTURE.SSRF")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or host in BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError("RT.CAPTURE.SSRF")
    try:
        ipaddress.ip_address(host)
        raise ValueError("RT.CAPTURE.SSRF")
    except ValueError as exc:
        if str(exc) == "RT.CAPTURE.SSRF":
            raise
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("RT.CAPTURE.FETCH_FAILED") from exc
    for info in infos:
        sockaddr = info[4]
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise ValueError("RT.CAPTURE.SSRF")
    return url


def fetch_public_url(url: str, limit: int = 20000) -> tuple[str, str]:
    safe = assert_public_http_url(url)
    request = Request(
        safe,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=20, context=ssl_context()) as response:
            if response.status >= 400:
                raise ValueError("RT.CAPTURE.FETCH_FAILED")
            raw = response.read(800_000)
    except HTTPError as exc:
        raise ValueError("RT.CAPTURE.FETCH_FAILED") from exc
    except (URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        raise ValueError("RT.CAPTURE.FETCH_FAILED") from exc
    html = raw.decode("utf-8", errors="ignore")
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("RT.CAPTURE.FETCH_FAILED") from exc
    body = parser.text()[:limit]
    if len(body) < 80:
        raise ValueError("RT.CAPTURE.FETCH_FAILED")
    title = parser.title or parser.description or safe
    return title, body
