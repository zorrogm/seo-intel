"""Render only the pages that need JavaScript."""
from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter, deque
from typing import Dict, List, Tuple
from urllib.parse import urlsplit

from seo_intel import config
from seo_intel.corpus import _parsed
from seo_intel.crawl import RobotsRules
from seo_intel.extract import parse_page
from seo_intel.fetch import Fetcher
from seo_intel.store import Store
from seo_intel.text import tokenize
from seo_intel.urls import site_key

_DIGITS = re.compile(r"\d+")


def summarise(parsed: Dict) -> Dict:
    """The few numbers rendering decisions need."""
    words = sum(len(tokenize(block[2])) for block in parsed["blocks"])
    scripted = (parsed.get("script_bytes", 0) >= config.RENDER_MIN_SCRIPT_BYTES
                or parsed.get("external_scripts", 0) >= 1)
    thin = words < config.RENDER_THIN_WORDS and scripted
    told = bool(parsed.get("noscript_js")) and words < config.RENDER_NOSCRIPT_WORDS
    return {
        "words": words,
        "links": len({link[0] for block in parsed["blocks"] for link in block[3]}),
        "title": parsed["title"],
        "canonical": parsed["canonical"],
        "meta_robots": parsed["meta_robots"],
        # Thin text with heavy scripts, from raw HTML
        "script_built": thin or told,
    }


def url_shape(url: str) -> str:
    """Pages of one template share a shape."""
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    first = _DIGITS.sub("N", segments[0]) if segments else ""
    return f"/{first}/depth{len(segments)}" + ("?" if parts.query else "")


def differs(raw: Dict, rendered: Dict) -> bool:
    """Did rendering add real content or links?"""
    before, after = raw["words"], rendered["words"]
    grew = after >= before * config.RENDER_WORD_GROWTH
    if grew and after - before >= config.RENDER_MIN_NEW_WORDS:
        return True
    links_before, links_after = raw["links"], rendered["links"]
    more = links_after >= links_before * config.RENDER_WORD_GROWTH
    if more and links_after - links_before >= config.RENDER_MIN_NEW_LINKS:
        return True
    return any(raw[name] != rendered[name] for name in ("title", "canonical", "meta_robots"))


def _order(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


class RenderPlan:
    """Decides what to render for one site."""

    def __init__(self, store: Store, site: str):
        rows = [r for r in store.fetched_rows(site) if r[2] == 200 and r[5] and not r[3]]
        self.store = store
        self.site = site
        self.ids = {r[1]: r[0] for r in rows}
        store.db.execute("BEGIN")
        self.parsed = {r[1]: summarise(_parsed(store, r[0], r[1], r[5])) for r in rows}
        store.db.execute("COMMIT")
        self.cap = int(config.MAX_RENDER_SHARE * len(rows))
        self.shapes: Dict[str, List[str]] = {}
        for url in sorted(self.parsed):
            self.shapes.setdefault(url_shape(url), []).append(url)
        self.rendered = 0

    def first_queue(self) -> List[Tuple[str, str]]:
        """Suspicious pages, then samples of each template."""
        queue = [(url, "raw HTML looks script built")
                 for url in sorted(self.parsed) if self.parsed[url]["script_built"]]
        picked = {url for url, _why in queue}
        for shape in sorted(self.shapes):
            urls = self.shapes[shape]
            if len(urls) < config.RENDER_SHAPE_MIN_PAGES:
                continue
            for url in sorted(urls, key=_order)[: config.RENDER_SAMPLES_PER_SHAPE]:
                if url not in picked:
                    picked.add(url)
                    queue.append((url, "template sample"))
        return queue

    def follow_up(self, results: Dict[str, bool], done: set) -> List[Tuple[str, str]]:
        """Whole templates whose samples changed when rendered."""
        queue = []
        for shape in sorted(self.shapes):
            urls = self.shapes[shape]
            tested = [u for u in urls if u in results]
            changed = sum(results[u] for u in tested)
            if tested and changed * 2 > len(tested):
                queue.extend((u, "template needs JavaScript") for u in urls if u not in done)
        return queue


async def _render_site(plan: RenderPlan, browser, limits: Fetcher, robots: RobotsRules,
                       deadline: float) -> None:
    loop = asyncio.get_running_loop()
    context = await browser.new_context(user_agent=config.USER_AGENT)

    async def gate(route):
        """Same politeness rules as the crawler."""
        request = route.request
        if request.resource_type in config.RENDER_BLOCKED_RESOURCES:
            return await route.abort()
        if site_key(request.url) == plan.site and not await robots.allowed(request.url):
            return await route.abort()
        await limits._limiter(request.url).wait()
        await route.continue_()

    await context.route("**/*", gate)
    results: Dict[str, bool] = {}
    done = set()

    async def render(url: str, reason: str) -> None:
        page = await context.new_page()
        try:
            try:
                await page.goto(url, wait_until="networkidle",
                                timeout=config.RENDER_PAGE_TIMEOUT_SECONDS * 1000)
            except Exception:
                # Slow pages still give partial content
                pass
            html = (await page.content()).encode("utf-8")
        except Exception:
            return
        finally:
            await page.close()
        raw = plan.parsed[url]
        rendered = summarise(parse_page(html, url))
        changed = differs(raw, rendered)
        results[url] = changed
        plan.store.save_render(plan.ids[url], html, reason, raw["words"],
                               rendered["words"], changed)

    async def drain(queue) -> None:
        async def tab():
            while queue and plan.rendered < plan.cap and loop.time() < deadline:
                url, reason = queue.popleft()
                if url in done:
                    continue
                done.add(url)
                plan.rendered += 1
                await render(url, reason)
        await asyncio.gather(*(tab() for _ in range(config.RENDER_TABS)))
        # Out of budget: still report what needs it
        for url, reason in queue:
            if url not in done and reason != "template sample":
                done.add(url)
                plan.store.flag_render(plan.ids[url], reason, plan.parsed[url]["words"])

    await drain(deque(plan.first_queue()))
    await drain(deque(plan.follow_up(results, done)))
    await context.close()


async def _render_all(store: Store, sites: List[str], gap_seconds: float) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return "skipped: browser library not installed"
    limits = Fetcher(gap_seconds)
    robots = RobotsRules(limits, store)
    deadline = asyncio.get_running_loop().time() + config.RENDER_MINUTES * 60
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                plans = [RenderPlan(store, site) for site in sites]
                await asyncio.gather(*(_render_site(p, browser, limits, robots, deadline)
                                       for p in plans))
            finally:
                await browser.close()
    except Exception as exc:
        # A broken browser must never stop the run
        return f"skipped: browser failed ({type(exc).__name__})"
    finally:
        await limits.close()
    return "done"


def render_stage(store: Store, sites: List[str], gap_seconds: float) -> None:
    """Runs once per crawl; later runs reuse it."""
    if store.get_meta("render_state"):
        return
    state = asyncio.run(_render_all(store, sorted(set(sites)), gap_seconds))
    store.set_meta("render_state", state)


def render_report(store: Store, sites: List[str]) -> Dict:
    report: Dict = {"state": store.get_meta("render_state") or "not run", "sites": {}}
    for site in sorted(set(sites)):
        rows = store.renders(site)
        pages = sum(1 for r in store.fetched_rows(site) if r[2] == 200 and r[5])
        shown = [row for row in rows if row[3] >= 0]
        reasons = Counter(row[1] for row in rows)
        report["sites"][site] = {
            "html_pages": pages,
            "rendered": len(shown),
            "rendered_share": round(len(shown) / pages, config.FLOAT_DIGITS) if pages else 0.0,
            "changed_by_rendering": sum(row[4] for row in shown),
            "flagged_but_not_rendered": len(rows) - len(shown),
            "why": dict(sorted(reasons.items())),
            "pages": [
                {"url": url, "reason": reason, "words_raw": raw,
                 "words_rendered": rendered if rendered >= 0 else None,
                 "needs_javascript": bool(changed), "rendered": rendered >= 0}
                for url, reason, raw, rendered, changed in rows
            ],
        }
    return report
