"""Load crawled pages into memory for analysis."""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from seo_intel import config
from seo_intel.extract import is_template, learn_template, parse_page
from seo_intel.soft404 import soft_404_reason
from seo_intel.store import Store
from seo_intel.text import sentences, tokenize


@dataclass
class Page:
    url: str
    site: str
    status: int
    redirect_to: str = ""
    redirect_kind: str = ""
    x_robots: str = ""
    soft_404: str = ""
    lang: str = ""
    total_words: int = 0
    title: str = ""
    h1: str = ""
    canonical: str = ""
    meta_robots: str = ""
    hreflang: List[str] = field(default_factory=list)
    sentences: List[str] = field(default_factory=list)
    tokens: List[str] = field(default_factory=list)
    # target URL, anchor text, in content flag
    links: List[Tuple[str, str, bool]] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.tokens)

    @property
    def noindex(self) -> bool:
        rules = self.meta_robots + "," + self.x_robots.lower()
        return "noindex" in rules or "none" in rules

    @property
    def indexable(self) -> bool:
        """A normal page search engines can show."""
        if self.status != 200 or self.redirect_to or self.soft_404 or self.noindex:
            return False
        return self.canonical in ("", self.url)


def _parsed(store: Store, url_id: int, url: str, body_hash: str) -> Dict:
    # Old parses are redone after a parser change
    key = f"{body_hash}:v{config.PARSE_VERSION}"
    cached = store.get_parsed(url_id, key)
    if cached is not None:
        return json.loads(cached)
    data = parse_page(store.body(url_id), url)
    store.save_parsed(url_id, key, json.dumps(data, ensure_ascii=False).encode("utf-8"))
    return data


def _sample_order(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _fill(page: Page, data: Dict, template) -> None:
    page.title = data["title"]
    page.h1 = data["h1"]
    page.canonical = data["canonical"]
    page.meta_robots = data["meta_robots"]
    page.hreflang = data["hreflang"]
    main_blocks = []
    for block in data["blocks"]:
        in_content = not is_template(block, template)
        page.total_words += len(tokenize(block[2]))
        if in_content and block[2]:
            main_blocks.append(block[2])
        for target, anchor in block[3]:
            page.links.append((target, anchor, in_content))
    page.lang = data.get("lang", "")
    page.sentences = [s for b in main_blocks for s in sentences(b)]
    # Shared word objects keep memory low
    page.tokens = [sys.intern(t) for t in tokenize("\n".join(main_blocks))]
    if not page.lang and page.tokens:
        # No lang tag: guess Hindi from the script
        hindi = sum("\u0900" <= t[0] <= "\u097f" for t in page.tokens)
        if hindi / len(page.tokens) >= config.DEVANAGARI_MIN_SHARE:
            page.lang = "hi"


def _probe_page(store: Store, site: str, template) -> Optional[Page]:
    """The answer to a URL that cannot exist."""
    rows = store.fetched_rows(config.PROBE_SITE_PREFIX + site)
    if not rows:
        return None
    url_id, url, status, redirect_to, _x, body_hash, _kind = rows[0]
    probe = Page(url=url, site=site, status=status, redirect_to=redirect_to)
    if body_hash:
        _fill(probe, parse_page(store.body(url_id), url), template)
    return probe


def load_site(store: Store, site: str, home: str = "") -> List[Page]:
    """All fetched pages of a site, sorted by URL."""
    rows = store.fetched_rows(site)
    html = {r[1]: (r[0], r[5]) for r in rows if r[2] == 200 and r[5]}

    def parsed(url: str) -> Dict:
        url_id, body_hash = html[url]
        return _parsed(store, url_id, url, body_hash)

    store.db.execute("BEGIN")
    # Learn the template from a fixed sample
    sample_urls = sorted(html, key=_sample_order)[: config.TEMPLATE_SAMPLE_PAGES]
    template = learn_template([parsed(u) for u in sample_urls])

    pages = []
    for _id, url, status, redirect_to, x_robots, _hash, kind in rows:
        page = Page(url=url, site=site, status=status, redirect_to=redirect_to,
                    redirect_kind=kind, x_robots=x_robots)
        if url in html:
            # One page in memory at a time
            _fill(page, parsed(url), template)
        pages.append(page)
    store.db.execute("COMMIT")

    probe = _probe_page(store, site, template)
    for page in pages:
        # The homepage is never a missing page
        if page.url != home and page.status == 200 and not page.redirect_to and page.url in html:
            page.soft_404 = soft_404_reason(page, probe)
    return pages
