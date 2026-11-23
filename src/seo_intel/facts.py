"""Look up and verify facts against the crawl store."""
from __future__ import annotations

from typing import Dict, Tuple

from seo_intel import config
from seo_intel.analysis import Analysis
from seo_intel.extract import parse_page
from seo_intel.store import Store
from seo_intel.text import jaccard
from seo_intel.topics import pair_similarity

PAGE_FIELDS = (
    "status", "title", "h1", "canonical", "redirect_to", "meta_robots",
    "intent", "inlinks", "click_depth", "word_count",
)
PAIR_METRICS = ("content_overlap", "topic_similarity", "links_to")
TOPIC_METRICS = ("pages", "words")
# These are re-read from the raw crawl
_RAW_FIELDS = ("title", "h1", "canonical", "meta_robots")


class Facts:
    def __init__(self, analysis: Analysis, store: Store):
        self.a = analysis
        self.store = store

    def knows(self, url: str) -> bool:
        return url in self.a.index

    def field(self, url: str, name: str):
        i = self.a.index[url]
        page = self.a.pages[i]
        if name == "intent":
            return self.a.intents[i]
        if name == "inlinks":
            return self.a.inlinks[i]
        if name == "click_depth":
            return self.a.depth[i]
        if name == "word_count":
            return page.word_count
        return getattr(page, name)

    def metric(self, url_a: str, url_b: str, name: str):
        a, b = self.a.index[url_a], self.a.index[url_b]
        if name == "content_overlap":
            overlap = jaccard(self.a.shingle_sets[a], self.a.shingle_sets[b])
            return round(overlap, config.FLOAT_DIGITS)
        if name == "topic_similarity":
            row_a, row_b = self.a.row_of[a], self.a.row_of[b]
            cosine = pair_similarity(row_a, row_b, self.a.sparse, self.a.heads)
            return round(cosine, config.FLOAT_DIGITS)
        if name == "links_to":
            return (a, b) in self.a.edges
        raise KeyError(name)

    def topic_stat(self, topic_id: int, site: str, name: str) -> int:
        """Pages or words a site has in a topic."""
        for gap in self.a.gaps:
            if gap["topic_id"] == topic_id:
                side = "target" if site == self.a.target_site else "competitor"
                return gap[f"{side}_{name}"]
        raise KeyError(topic_id)

    def _raw_field(self, url: str, name: str):
        """Parse the stored HTML again, skipping caches."""
        row = self.store.db.execute(
            "SELECT p.status, p.redirect_to, u.id FROM pages p JOIN urls u"
            " ON u.id = p.url_id WHERE u.url=?", (url,)
        ).fetchone()
        if row is None:
            raise KeyError(url)
        if name == "status":
            return row[0]
        if name == "redirect_to":
            return row[1]
        body = self.store.body(row[2])
        return parse_page(body, url)[name] if body else ""

    def check(self, claim: Dict) -> Tuple[bool, object]:
        """True when the claim matches the crawl."""
        try:
            if "topic_id" in claim:
                if claim["metric"] not in TOPIC_METRICS:
                    return False, "unknown metric"
                actual = self.topic_stat(claim["topic_id"], claim["site"], claim["metric"])
            elif "metric" in claim:
                if claim["metric"] not in PAIR_METRICS:
                    return False, "unknown metric"
                actual = self.metric(claim["url_a"], claim["url_b"], claim["metric"])
            elif claim.get("field") == "sentence":
                page = self.a.pages[self.a.index[claim["url"]]]
                return claim["value"] in page.sentences, "sentence lookup"
            elif claim.get("field") in _RAW_FIELDS + ("status", "redirect_to"):
                actual = self._raw_field(claim["url"], claim["field"])
            elif claim.get("field") in PAGE_FIELDS:
                actual = self.field(claim["url"], claim["field"])
            else:
                return False, "unknown field"
        except (KeyError, IndexError):
            return False, "not in crawl"
        return actual == claim["value"] and type(actual) is type(claim["value"]), actual
