"""Polite HTTP fetching with a per host speed limit."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urlsplit

import httpx

from seo_intel import config

_RETRY_STATUSES = (429, 502, 503, 504)


@dataclass
class FetchResult:
    status: int = 0
    error: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    location: str = ""
    truncated: bool = False

    def header(self, name: str) -> str:
        return self.headers.get(name, "")

    def is_html(self) -> bool:
        kind = self.header("content-type").split(";")[0].strip().lower()
        return kind in config.HTML_CONTENT_TYPES


class HostLimiter:
    """Spaces out request starts for one host."""

    def __init__(self, gap_seconds: float):
        self.gap = gap_seconds
        self.next_at = 0.0
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            loop = asyncio.get_running_loop()
            wait = self.next_at - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            # Measure from the real start, never bunch
            self.next_at = loop.time() + self.gap


class Fetcher:
    def __init__(self, gap_seconds: float = config.REQUEST_GAP_SECONDS):
        self.gap = gap_seconds
        self.limiters: Dict[str, HostLimiter] = {}
        self.requests = 0
        timeout = httpx.Timeout(
            config.READ_TIMEOUT_SECONDS, connect=config.CONNECT_TIMEOUT_SECONDS
        )
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": config.USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    def _limiter(self, url: str) -> HostLimiter:
        host = urlsplit(url).netloc
        if host not in self.limiters:
            self.limiters[host] = HostLimiter(self.gap)
        return self.limiters[host]

    async def _once(self, url: str, max_bytes: int, any_type: bool, headers) -> FetchResult:
        result = FetchResult()
        await self._limiter(url).wait()
        self.requests += 1
        try:
            async with self.client.stream("GET", url, headers=headers) as response:
                result.status = response.status_code
                result.headers = {k.lower(): v for k, v in response.headers.items()}
                result.location = result.header("location")
                # Skip bodies we cannot use
                if not (any_type or result.is_html()):
                    return result
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= max_bytes:
                        result.truncated = True
                        break
                result.body = b"".join(chunks)[:max_bytes]
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, OSError) as exc:
            result.status = 0
            result.body = b""
            result.error = type(exc).__name__
        return result

    def _retry_wait(self, result: FetchResult, attempt: int) -> float:
        try:
            wait = float(result.header("retry-after"))
        except ValueError:
            wait = 2.0 ** attempt
        return min(max(wait, 0.0), config.MAX_RETRY_WAIT_SECONDS)

    async def get(
        self, url: str, max_bytes: int = config.MAX_BODY_BYTES, any_type: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ) -> FetchResult:
        """Fetch one URL, retrying temporary failures."""
        result = FetchResult()
        for attempt in range(config.FETCH_RETRIES + 1):
            result = await self._once(url, max_bytes, any_type, headers)
            if result.status and result.status not in _RETRY_STATUSES:
                break
            if attempt < config.FETCH_RETRIES:
                await asyncio.sleep(self._retry_wait(result, attempt))
        return result
