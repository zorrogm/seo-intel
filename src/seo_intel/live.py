"""Re-fetch cited pages right before the plan is written."""
from __future__ import annotations

import asyncio
from typing import Dict, Iterable, List, Optional

from seo_intel import config
from seo_intel.crawl import RobotsRules
from seo_intel.extract import parse_page
from seo_intel.fetch import Fetcher
from seo_intel.links import scan_page
from seo_intel.store import Store
from seo_intel.text import clean
from seo_intel.urls import normalize


class LiveCheck:
    """Current state of pages the plan cites."""

    def __init__(self, store: Store, gap_seconds: float):
        self.store = store
        self.gap_seconds = gap_seconds
        self.pages: Dict[str, Optional[Dict]] = {}

    async def _fetch_all(self, urls: List[str]) -> None:
        fetcher = Fetcher(self.gap_seconds)
        robots = RobotsRules(fetcher, self.store)
        try:
            await asyncio.gather(*(self._fetch(fetcher, robots, url) for url in urls))
        finally:
            await fetcher.close()

    async def _fetch(self, fetcher: Fetcher, robots: RobotsRules, url: str) -> None:
        self.pages[url] = None
        if not await robots.allowed(url):
            return
        result = await fetcher.get(url)
        if result.status == 0:
            return
        page = {"status": result.status, "redirect_to": "", "title": "", "h1": "",
                "canonical": "", "meta_robots": "", "text": ""}
        if 300 <= result.status < 400:
            page["redirect_to"] = normalize(result.location, url) or ""
        elif result.body and result.is_html():
            page["redirect_to"] = scan_page(result.body, url).redirect_to
            parsed = parse_page(result.body, url)
            page.update({name: parsed[name] for name in ("title", "h1", "canonical", "meta_robots")})
            page["text"] = clean(" ".join(block[2] for block in parsed["blocks"]))
        self.pages[url] = page

    def fetch(self, urls: Iterable[str]) -> None:
        todo = sorted(set(urls) - set(self.pages))
        if todo:
            asyncio.run(self._fetch_all(todo))

    def pending(self, actions: List[Dict]) -> List[str]:
        """Cited URLs not yet rechecked."""
        urls = set()
        for action in actions:
            for claim in action["claims"]:
                if claim.get("field") in config.LIVE_FIELDS and claim["url"] not in self.pages:
                    urls.add(claim["url"])
        return sorted(urls)

    def verdict(self, claim: Dict) -> Optional[bool]:
        """True, False, or None when we cannot tell."""
        name = claim.get("field")
        if name not in config.LIVE_FIELDS:
            return None
        page = self.pages.get(claim["url"])
        if page is None:
            return None
        if name == "sentence":
            return clean(claim["value"]) in page["text"]
        return page[name] == claim["value"]
