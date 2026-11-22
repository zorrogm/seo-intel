"""Crawl two sites side by side, safely resumable."""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import html
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Set, Union

from seo_intel import config
from seo_intel.fetch import Fetcher
from seo_intel.extract import parse_page
from seo_intel.fetch import FetchResult
from seo_intel.links import scan_page
from seo_intel.robots import RobotsTxt
from seo_intel.store import BLOCKED, FETCHED, QUEUED, Job, Store
from seo_intel.traps import TrapGuard
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
        self.guard = TrapGuard()
        # Set during a next day rerun
        self.run_number = 0
        self.min_id = 0
        self.seeding = False

    def in_scope(self, url: str) -> bool:
        return site_key(url) == self.site and not looks_like_file(url)

    def accept(self, url: str) -> bool:
        """In scope and not a spider trap."""
        if not self.in_scope(url):
            return False
        trap = self.guard.check(url)
        if trap:
            self.store.add_trap(self.site, trap[0], trap[1], url)
            return False
        return True

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

    async def _seed_sitemaps(self, start: str, again: bool = False) -> None:
        if self.store.get_meta("sitemaps:" + self.site) and not again:
            return
        policy = await self.robots.policy(start)
        listed = [] if isinstance(policy, bool) else policy.sitemaps
        todo = deque(u for u in (normalize(s, start) for s in listed) if u)
        if not todo:
            todo.append(origin(start) + "/sitemap.xml")
        seen = set(todo)
        fetched = added = 0
        loop = asyncio.get_running_loop()
        while (todo and fetched < config.MAX_SITEMAP_FILES
               and added < config.MAX_SITEMAP_URLS and loop.time() < self.deadline):
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
                room = config.MAX_SITEMAP_URLS - added
                wanted = [u for u in locs if self.accept(u)][:room]
                added += self.store.add_urls(self.site, wanted, config.SITEMAP_DEPTH)
        self.store.set_meta("sitemaps:" + self.site, "done")

    async def _probe_missing_page(self, start: str) -> None:
        """Ask for a page that cannot exist."""
        key = "probe:" + self.site
        if self.store.get_meta(key):
            return
        name = hashlib.sha1(self.site.encode("utf-8")).hexdigest()[:16]
        url = origin(start) + config.PROBE_PATH_PREFIX + name
        if await self.robots.allowed(url):
            probe_site = config.PROBE_SITE_PREFIX + self.site
            self.store.add_urls(probe_site, [url], 0)
            result = await self.fetcher.get(url)
            target = normalize(result.location, url) if result.location else None
            result.location = target or ""
            self.store.save_fetch((self.store.url_id(url), url, 0), probe_site, result, [])
        self.store.set_meta(key, "done")

    def _next_job(self):
        if not self.ready:
            batch = self.store.take(self.site, config.FRONTIER_BATCH, self.busy, self.min_id)
            self.ready.extend(batch)
        if not self.ready:
            return None
        job = self.ready.popleft()
        self.busy.add(job[0])
        return job

    def _save(self, job: Job, result: FetchResult):
        """Scan the response, store it, queue its links."""
        url = job[1]
        new_urls: List[str] = []
        kind = ""
        scan = None
        if 300 <= result.status < 400:
            target = normalize(result.location, url) if result.location else None
            result.location = target or ""
            kind = "http" if target else ""
            if target and self.accept(target):
                new_urls = [target]
        elif result.status == 200 and result.body and result.is_html():
            scan = scan_page(result.body, url)
            for name in scan.session_params:
                self.store.add_trap(self.site, "session_id", f"parameter {name}", url)
            header = result.header("x-robots-tag").lower()
            follow = not (scan.nofollow or "nofollow" in header or "none" in header)
            if scan.redirect_to:
                result.location, kind = scan.redirect_to, scan.redirect_kind
                new_urls = [scan.redirect_to] if self.accept(scan.redirect_to) else []
            elif follow:
                new_urls = [u for u in scan.links if self.accept(u)]
        self.store.save_fetch(job, self.site, result, new_urls, kind)
        return scan

    async def _handle(self, job: Job) -> None:
        url_id, url, _depth = job
        if not await self.robots.allowed(url):
            self.store.mark(url_id, BLOCKED)
            return
        result = await self.fetcher.get(url)
        self._save(job, result)
        if self.run_number and result.status == 200:
            self.store.add_change(self.run_number, self.site, url, "new")

    async def _recheck(self, row) -> None:
        """Ask the server if a known page changed."""
        url_id, url, depth, status, etag, modified, body_hash, redirect_to = row
        if not await self.robots.allowed(url):
            return
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        result = await self.fetcher.get(url, headers=headers)
        # Unchanged, or the request failed: keep ours
        if result.status in (0, 304):
            return
        run, site = self.run_number, self.site
        gone = result.status in (404, 410)
        moved = 300 <= result.status < 400
        if result.status == 200 and result.body and result.is_html():
            if hashlib.sha256(result.body).hexdigest() == body_hash:
                return
            old = parse_page(self.store.raw_body(url_id), url) if status == 200 and body_hash else None
            scan = self._save((url_id, url, depth), result)
            if old is None:
                return
            if scan.redirect_to and not redirect_to:
                self.store.add_change(run, site, url, "newly_redirected", "", scan.redirect_to)
            new = parse_page(result.body, url)
            for name in ("title", "canonical"):
                if old[name] != new[name]:
                    self.store.add_change(run, site, url, name + "_changed", old[name], new[name])
        elif moved or gone:
            was_page = status == 200 and not redirect_to
            self._save((url_id, url, depth), result)
            if was_page and moved:
                self.store.add_change(run, site, url, "newly_redirected", "", result.location)
            elif was_page and gone:
                self.store.add_change(run, site, url, "removed")

    async def _worker(self) -> None:
        loop = asyncio.get_running_loop()
        while loop.time() < self.deadline:
            job = self._next_job()
            if job is None:
                # Done when nobody can add more
                if not self.busy and not self.seeding:
                    return
                await asyncio.sleep(config.IDLE_POLL_SECONDS)
                continue
            try:
                await self._handle(job)
            finally:
                self.busy.discard(job[0])

    async def _rechecker(self, rows: Deque) -> None:
        loop = asyncio.get_running_loop()
        while rows and loop.time() < self.deadline:
            await self._recheck(rows.popleft())

    def summary(self) -> Dict[str, int]:
        return {
            "known": self.store.count(self.site),
            "fetched": self.store.count(self.site, FETCHED),
            "queued": self.store.count(self.site, QUEUED),
            "blocked": self.store.count(self.site, BLOCKED),
        }

    async def _seed_in_background(self, start: str, again: bool = False) -> None:
        """Read sitemaps while pages are already being fetched."""
        self.seeding = True
        try:
            await self._seed_sitemaps(start, again)
        finally:
            self.seeding = False

    async def _prepare(self) -> str:
        start = await self._find_start()
        self.site = site_key(start)
        # Rebuild trap memory after a restart
        for url in self.store.site_urls(self.site):
            self.guard.check(url)
        return start

    async def run(self, mode: str, run_number: int = 0) -> None:
        start = await self._prepare()
        workers = range(config.WORKERS_PER_SITE)
        if mode == "crawl":
            self.store.add_urls(self.site, [start], 0)
            await self._probe_missing_page(start)
            await asyncio.gather(self._seed_in_background(start),
                                 *(self._worker() for _ in workers))
        elif mode == "revalidate":
            self.run_number = run_number
            rows = deque(self.store.revalidation_rows(self.site))
            # Only URLs found from now on are new
            self.min_id = self.store.max_id() + 1
            await asyncio.gather(self._seed_in_background(start, again=True),
                                 *(self._rechecker(rows) for _ in workers))
            await asyncio.gather(*(self._worker() for _ in workers))


def _seconds_used(store: Store) -> float:
    return float(store.get_meta("crawl_seconds") or 0)


async def _progress(crawls: List[SiteCrawl], store: Store, count_time: bool) -> None:
    while True:
        await asyncio.sleep(config.PROGRESS_SECONDS)
        # Remember time spent, for resume after kill
        if count_time:
            used = _seconds_used(store) + config.PROGRESS_SECONDS
            store.set_meta("crawl_seconds", str(used))
        parts = [f"{c.domain}: {c.summary()['fetched']} fetched" for c in crawls if c.site]
        print("  " + ", ".join(parts), file=sys.stderr, flush=True)


def _mode(store: Store, revalidate_after_hours: float) -> str:
    """Crawl, revalidate, or reuse the frozen crawl."""
    if store.get_meta("crawl_done") is None:
        return "crawl"
    age = time.time() - float(store.get_meta("last_crawl_time") or 0)
    return "revalidate" if age >= revalidate_after_hours * 3600 else "reuse"


async def crawl_sites(
    domains: List[str],
    run_dir: Path,
    minutes: float = config.CRAWL_MINUTES,
    max_urls: int = config.MAX_URLS_PER_SITE,
    gap_seconds: float = config.REQUEST_GAP_SECONDS,
    revalidate_after_hours: float = config.REVALIDATE_AFTER_HOURS,
) -> Dict[str, Dict[str, int]]:
    """Crawl every domain until done or out of time."""
    store = Store(run_dir / config.CRAWL_DB_NAME, max_urls)
    fetcher = Fetcher(gap_seconds)
    robots = RobotsRules(fetcher, store)
    mode = _mode(store, revalidate_after_hours)
    run_number = int(store.get_meta("runs") or 0) + 1
    seconds = minutes * 60
    if mode == "crawl":
        seconds = max(0.0, seconds - _seconds_used(store))
    elif mode == "revalidate":
        seconds *= config.REVALIDATE_SHARE
    deadline = asyncio.get_running_loop().time() + seconds
    crawls = [SiteCrawl(store, fetcher, robots, d, deadline) for d in domains]
    progress = asyncio.ensure_future(_progress(crawls, store, mode == "crawl"))
    try:
        await asyncio.gather(*(c.run(mode, run_number) for c in crawls))
        if mode != "reuse":
            # A finished crawl is frozen, never extended
            store.set_meta("crawl_done", "1")
            store.set_meta("runs", str(run_number))
            store.set_meta("last_crawl_time", str(time.time()))
        return {c.domain: dict(c.summary(), site=c.site, mode=mode) for c in crawls}
    finally:
        progress.cancel()
        await fetcher.close()
        store.close()
