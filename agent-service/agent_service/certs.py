"""Install a real CA bundle for Homebrew Python/OpenSSL.

Homebrew OpenSSL often points at an empty cert.pem, so HTTPS verify
fails even for public sites. This does not disable verification.
"""

from __future__ import annotations

import os
import ssl
from pathlib import Path

_MIN_BUNDLE_BYTES = 2048


def ca_bundle_path() -> str:
    candidates: list[str] = []
    try:
        import certifi

        candidates.append(certifi.where())
    except Exception:  # noqa: BLE001
        pass
    candidates.extend(
        [
            os.environ.get("SSL_CERT_FILE") or "",
            "/etc/ssl/cert.pem",
            "/opt/homebrew/etc/openssl@3/cert.pem",
            "/usr/local/etc/openssl@3/cert.pem",
        ]
    )
    for path in candidates:
        if _usable(path):
            return path
    raise RuntimeError("RT.CAPTURE.NO_CA_BUNDLE")


def _usable(path: str) -> bool:
    if not path:
        return False
    file = Path(path)
    try:
        return file.is_file() and file.stat().st_size >= _MIN_BUNDLE_BYTES
    except OSError:
        return False


def ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=ca_bundle_path())


def install_trust_store() -> str:
    path = ca_bundle_path()
    os.environ.setdefault("SSL_CERT_FILE", path)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", path)
    os.environ.setdefault("CURL_CA_BUNDLE", path)
    ssl._create_default_https_context = ssl_context  # noqa: SLF001
    return path
