"""Crawl two sites side by side, safely resumable."""
from __future__ import annotations

import asyncio
import gzip
import html
import re
import sys
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Set, Union

from seo_intel import config
from seo_intel.fetch import Fetcher
from seo_intel.links import extract_links
from seo_intel.robots import RobotsTxt
from seo_intel.store import BLOCKED, FETCHED, QUEUED, Job, Store
from seo_intel.urls import looks_like_file, normalize, origin, site_key, start_url

_LOC = re.compile(rb"<loc>\s*(.*?)\s*</loc>", re.S | re.I)
_CDATA = re.compile(r"^<!\[CDATA\[(.*)\]\]>$", re.S)

Policy = Union[bool, RobotsTxt]


class RobotsRules:
    """Fetches robots.txt once per origin."""

    def __init__(self, fetcher: Fetcher, store: Store):
        self.fetcher = fetcher
        self.store = store
        self.policies: Dict[str, Policy] = {}
        self.locks: Dict[str, asyncio.Lock] = {}

    async def _load(self, site_origin: str) -> Policy:
        url = site_origin + "/robots.txt"
        result = None
        for _hop in range(config.ROBOTS_MAX_REDIRECTS + 1):
            result = await self.fetcher.get(url, config.ROBOTS_MAX_FILE_BYTES, any_type=True)
            target = normalize(result.location, url) if result.location else None
            if not (300 <= result.status < 400 and target):
                break
            url = target
        self.store.save_robots(site_origin, result.status, result.body)
        if 200 <= result.status < 300:
            return RobotsTxt(result.body)
        # Google: missing file means crawl everything
        if 400 <= result.status < 500:
            return True
        # Server errors mean crawl nothing
        return False

    async def policy(self, url: str) -> Policy:
        site_origin = origin(url)
        lock = self.locks.setdefault(site_origin, asyncio.Lock())
        async with lock:
            if site_origin not in self.policies:
                self.policies[site_origin] = await self._load(site_origin)
        return self.policies[site_origin]

    async def allowed(self, url: str) -> bool:
        policy = await self.policy(url)
        if isinstance(policy, bool):
            return policy
        return policy.allowed(config.USER_AGENT_TOKEN, url)


def sitemap_locs(body: bytes) -> List[str]:
    """Every loc value in a sitemap file."""
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except (OSError, EOFError):
            return []
    locs = []
    for raw in _LOC.findall(body):
        text = raw.decode("utf-8", "replace").strip()
        cdata = _CDATA.match(text)
        locs.append(html.unescape(cdata.group(1).strip() if cdata else text))
    return locs


class SiteCrawl:
    def __init__(self, store: Store, fetcher: Fetcher, robots: RobotsRules,
                 domain: str, deadline: float):
        self.store = store
        self.fetcher = fetcher
        self.robots = robots
        self.domain = domain
        self.deadline = deadline
        self.site = ""
        self.busy: Set[int] = set()
        self.ready: Deque[Job] = deque()

    def in_scope(self, url: str) -> bool:
        return site_key(url) == self.site and not looks_like_file(url)

    async def _find_start(self) -> str:
        """Follow the homepage redirects to the real site."""
        saved = self.store.get_meta("start:" + self.domain)
        if saved:
            return saved
        url = start_url(self.domain) or ""
        for _hop in range(config.START_MAX_REDIRECTS):
            result = await self.fetcher.get(url, max_bytes=1)
            # Try plain http when https is dead
            if result.status == 0 and url.startswith("https://") and "://" not in self.domain:
                url = "http://" + url[len("https://"):]
                continue
            target = normalize(result.location, url) if result.location else None
            if not (300 <= result.status < 400 and target):
                break
            url = target
        self.store.set_meta("start:" + self.domain, url)
        return url

    async def _seed_sitemaps(self, start: str) -> None:
        if self.store.get_meta("sitemaps:" + self.site):
            return
        policy = await self.robots.policy(start)
        listed = [] if isinstance(policy, bool) else policy.sitemaps
        todo = deque(u for u in (normalize(s, start) for s in listed) if u)
        if not todo:
            todo.append(origin(start) + "/sitemap.xml")
        seen = set(todo)
        fetched = 0
        while todo and fetched < config.MAX_SITEMAP_FILES:
            result = await self.fetcher.get(
                todo.popleft(), config.SITEMAP_MAX_BYTES, any_type=True
            )
            fetched += 1
            if result.status != 200:
                continue
            locs = [u for u in (normalize(loc) for loc in sitemap_locs(result.body)) if u]
            if b"<sitemapindex" in result.body[:2000].lower():
                for loc in locs:
                    if loc not in seen:
                        seen.add(loc)
                        todo.append(loc)
            else:
                self.store.add_urls(self.site, (u for u in locs if self.in_scope(u)), 1)
        self.store.set_meta("sitemaps:" + self.site, "done")

    def _next_job(self):
        if not self.ready:
            self.ready.extend(self.store.take(self.site, config.FRONTIER_BATCH, self.busy))
        if not self.ready:
            return None
        job = self.ready.popleft()
        self.busy.add(job[0])
        return job

    async def _handle(self, job: Job) -> None:
        url_id, url, _depth = job
        if not await self.robots.allowed(url):
            self.store.mark(url_id, BLOCKED)
            return
        result = await self.fetcher.get(url)
        new_urls: List[str] = []
        if 300 <= result.status < 400:
            target = normalize(result.location, url) if result.location else None
            result.location = target or ""
            if target and self.in_scope(target):
                new_urls = [target]
        elif result.status == 200 and result.body and result.is_html():
            new_urls = [u for u in extract_links(result.body, url) if self.in_scope(u)]
        self.store.save_fetch(job, self.site, result, new_urls)

    async def _worker(self) -> None:
        loop = asyncio.get_running_loop()
        while loop.time() < self.deadline:
            job = self._next_job()
            if job is None:
                # Done when nobody can add more
                if not self.busy:
                    return
                await asyncio.sleep(config.IDLE_POLL_SECONDS)
                continue
            try:
                await self._handle(job)
            finally:
                self.busy.discard(job[0])

    def summary(self) -> Dict[str, int]:
        return {
            "known": self.store.count(self.site),
            "fetched": self.store.count(self.site, FETCHED),
            "queued": self.store.count(self.site, QUEUED),
            "blocked": self.store.count(self.site, BLOCKED),
        }

    async def run(self, crawl: bool) -> None:
        start = await self._find_start()
        self.site = site_key(start)
        if not crawl:
            return
        self.store.add_urls(self.site, [start], 0)
        await self._seed_sitemaps(start)
        await asyncio.gather(*(self._worker() for _ in range(config.WORKERS_PER_SITE)))


def _seconds_used(store: Store) -> float:
    return float(store.get_meta("crawl_seconds") or 0)


async def _progress(crawls: List[SiteCrawl], store: Store) -> None:
    while True:
        await asyncio.sleep(config.PROGRESS_SECONDS)
        # Remember time spent, for resume after kill
        store.set_meta("crawl_seconds", str(_seconds_used(store) + config.PROGRESS_SECONDS))
        parts = [f"{c.domain}: {c.summary()['fetched']} fetched" for c in crawls if c.site]
        print("  " + ", ".join(parts), file=sys.stderr, flush=True)


async def crawl_sites(
    domains: List[str],
    run_dir: Path,
    minutes: float = config.CRAWL_MINUTES,
    max_urls: int = config.MAX_URLS_PER_SITE,
    gap_seconds: float = config.REQUEST_GAP_SECONDS,
) -> Dict[str, Dict[str, int]]:
    """Crawl every domain until done or out of time."""
    store = Store(run_dir / config.CRAWL_DB_NAME, max_urls)
    fetcher = Fetcher(gap_seconds)
    robots = RobotsRules(fetcher, store)
    # A finished crawl is frozen, never extended
    crawl = store.get_meta("crawl_done") is None
    left = max(0.0, minutes * 60 - _seconds_used(store))
    deadline = asyncio.get_running_loop().time() + left
    crawls = [SiteCrawl(store, fetcher, robots, d, deadline) for d in domains]
    progress = asyncio.ensure_future(_progress(crawls, store))
    try:
        await asyncio.gather(*(c.run(crawl) for c in crawls))
        store.set_meta("crawl_done", "1")
        return {c.domain: dict(c.summary(), site=c.site) for c in crawls}
    finally:
        progress.cancel()
        await fetcher.close()
        store.close()
