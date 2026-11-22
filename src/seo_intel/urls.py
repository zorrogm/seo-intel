"""URL cleanup so one page has one address."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote, urljoin, urlsplit

from seo_intel import config

_SAFE_PATH = "/%:@!$&'()*+,;=~-._"
_SAFE_QUERY = "/%:@!$&'()*+,;=~-._?"
_ESCAPE = re.compile(r"%[0-9a-fA-F]{2}")
_JUNK = re.compile(r"[\t\r\n]")
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _remove_dot_segments(path: str) -> str:
    out = []
    for part in path.split("/"):
        if part == ".":
            continue
        if part == "..":
            if len(out) > 1:
                out.pop()
            continue
        out.append(part)
    # Keep the trailing slash after dots
    if path.endswith(("/.", "/..")):
        out.append("")
    return "/".join(out)


def _requote(text: str, safe: str) -> str:
    quoted = quote(text, safe=safe)
    return _ESCAPE.sub(lambda m: m.group(0).upper(), quoted)


def normalize(raw: str, base: Optional[str] = None) -> Optional[str]:
    """Return the clean absolute URL, or None."""
    raw = _JUNK.sub("", raw.strip())
    if not raw:
        return None
    try:
        parts = urlsplit(urljoin(base, raw) if base else raw)
        scheme = parts.scheme.lower()
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    path = _requote(_remove_dot_segments(parts.path or "/"), _SAFE_PATH)
    if not path.startswith("/"):
        path = "/" + path
    url = f"{scheme}://{netloc}{path}"
    if parts.query:
        url += "?" + _requote(parts.query, _SAFE_QUERY)
    if len(url) > config.MAX_URL_LENGTH:
        return None
    return url


def site_key(url: str) -> str:
    """Host and port without a leading www."""
    netloc = urlsplit(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def looks_like_file(url: str) -> bool:
    """True for images, scripts and other non pages."""
    return urlsplit(url).path.lower().endswith(config.SKIP_EXTENSIONS)


def start_url(domain: str) -> Optional[str]:
    """Turn a typed domain into a start URL."""
    domain = domain.strip()
    if "://" not in domain:
        domain = "https://" + domain
    return normalize(domain)
