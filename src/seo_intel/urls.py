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
_PATH_SESSION = re.compile(r";jsessionid=[^/?#]*", re.I)
_SESSION = frozenset(name.lower() for name in config.SESSION_PARAMS)
_NOISE = frozenset(config.NOISE_PARAMS) | _SESSION


def _is_noise(name: str) -> bool:
    name = name.lower()
    return name in _NOISE or name.startswith(config.NOISE_PARAM_PREFIXES)


def _clean_query(query: str) -> str:
    """Drop tracking and session parameters."""
    kept = [pair for pair in query.split("&") if pair and not _is_noise(pair.split("=")[0])]
    return "&".join(kept)


def session_param(raw: str) -> str:
    """Name of a session parameter in the URL."""
    if _PATH_SESSION.search(raw):
        return "jsessionid"
    for pair in urlsplit(raw).query.split("&"):
        if pair.split("=")[0].lower() in _SESSION:
            return pair.split("=")[0]
    return ""


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
    clean_path = _PATH_SESSION.sub("", parts.path or "/")
    path = _requote(_remove_dot_segments(clean_path), _SAFE_PATH)
    if not path.startswith("/"):
        path = "/" + path
    url = f"{scheme}://{netloc}{path}"
    query = _clean_query(parts.query)
    if query:
        url += "?" + _requote(query, _SAFE_QUERY)
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
