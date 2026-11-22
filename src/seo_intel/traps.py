"""Spot spider traps before they eat the crawl."""
from __future__ import annotations

import re
import time
from collections import Counter
from typing import Dict, Optional, Set, Tuple
from urllib.parse import urlsplit

from seo_intel import config

_DIGITS = re.compile(r"\d+")
_PATH_DATE = re.compile(r"/((?:19|20)\d{2})/(?:0?[1-9]|1[0-2])(?:/(?:0?[1-9]|[12]\d|3[01]))?/?$")
_QUERY_DATE = re.compile(r"=((?:19|20)\d{2})-(?:0[1-9]|1[0-2])(?:-\d{2})?(?:&|$)")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")

Trap = Tuple[str, str]


class TrapGuard:
    """Remembers URL patterns for one site."""

    def __init__(self):
        self.variants: Dict[str, Set[str]] = {}
        self.calendars: Dict[str, Set[str]] = {}
        self.last_year = time.gmtime().tm_year + config.CALENDAR_FUTURE_YEARS

    def _growing_path(self, path: str) -> Optional[Trap]:
        segments = [s for s in path.split("/") if s]
        if len(segments) > config.MAX_PATH_DEPTH:
            return "growing_path", f"more than {config.MAX_PATH_DEPTH} folders deep"
        if segments:
            segment, count = Counter(segments).most_common(1)[0]
            if count >= config.MAX_SEGMENT_REPEATS and not segment.isdigit():
                return "growing_path", f"folder '{segment}' repeats {count} times"
        return None

    def _faceted(self, path: str, query: str) -> Optional[Trap]:
        names = sorted({pair.split("=")[0] for pair in query.split("&")})
        pattern = f"{path}?{'&'.join(names)}"
        if len(names) > config.MAX_QUERY_PARAMS:
            return "faceted", pattern
        seen = self.variants.setdefault(path, set())
        if query not in seen:
            if len(seen) >= config.MAX_QUERY_VARIANTS_PER_PATH:
                return "faceted", f"{path}?* over {config.MAX_QUERY_VARIANTS_PER_PATH} filter mixes"
            seen.add(query)
        return None

    def _calendar(self, url: str, path: str, query: str) -> Optional[Trap]:
        years = []
        match = _PATH_DATE.search(path)
        if match:
            years.append(int(match.group(1)))
        years += [int(y) for y in _QUERY_DATE.findall(query)]
        for pair in query.split("&"):
            name, _sep, value = pair.partition("=")
            if name.lower() in config.CALENDAR_PARAMS and _YEAR.match(value):
                years.append(int(value))
            elif name.lower() in config.CALENDAR_PARAMS and value.isdigit():
                years.append(0)
        if not years:
            return None
        names = sorted({pair.split("=")[0] for pair in query.split("&") if pair})
        shape = _DIGITS.sub("N", path) + ("?" + "&".join(names) if names else "")
        real = [y for y in years if y]
        if any(y < config.CALENDAR_MIN_YEAR or y > self.last_year for y in real):
            return "calendar", f"{shape} dates outside sensible years"
        seen = self.calendars.setdefault(shape, set())
        if url not in seen:
            if len(seen) >= config.CALENDAR_MAX_PER_SHAPE:
                return "calendar", f"{shape} over {config.CALENDAR_MAX_PER_SHAPE} dates"
            seen.add(url)
        return None

    def check(self, url: str) -> Optional[Trap]:
        """Trap kind and pattern, or None if fine."""
        parts = urlsplit(url)
        trap = self._growing_path(parts.path)
        if trap is None and parts.query:
            trap = self._faceted(parts.path, parts.query)
        if trap is None:
            trap = self._calendar(url, parts.path, parts.query)
        return trap
