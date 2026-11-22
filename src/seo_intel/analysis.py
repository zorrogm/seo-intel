"""Run every analysis stage over the crawl store."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import numpy as np

from seo_intel import config, graph, similar, topics
from seo_intel.corpus import Page, load_site
from seo_intel.store import Store
from seo_intel.text import tokenize
from seo_intel.urls import normalize


@dataclass
class Analysis:
    target_site: str
    competitor_site: str
    pages: List[Page]
    index: Dict[str, int]
    target_count: int
    rows: List[int]
    row_of: Dict[int, int]
    vectors: np.ndarray
    labels: np.ndarray
    top_terms: List[List[str]]
    idf: Dict[str, float]
    intents: List[str]
    shingle_sets: List[Set[int]]
    anchors: Dict[int, List[str]]
    edges: graph.Edges
    rank: np.ndarray
    depth: List[int]
    inlinks: List[int]
    resolve: object
    near_duplicates: List[Dict] = field(default_factory=list)
    groups: List[Dict] = field(default_factory=list)
    healthy: List[Dict] = field(default_factory=list)
    gaps: List[Dict] = field(default_factory=list)
    priority: List[int] = field(default_factory=list)
    new_links: List[Dict] = field(default_factory=list)
    rank_after: Optional[np.ndarray] = None


def _default_priority(a: Analysis) -> List[int]:
    """Deep, wordy pages gain most from links."""
    deep = [
        i for i in range(a.target_count)
        if a.pages[i].indexable and i in a.row_of and a.depth[i] != 0 and a.depth[i] != 1
    ]
    deep.sort(key=lambda i: (-a.pages[i].word_count, a.pages[i].url))
    return deep[: config.DEFAULT_PRIORITY_COUNT]


def analyse(store: Store, target_site: str, competitor_site: str, start: str,
            seed: int, priority_urls: Optional[List[str]], budget: int) -> Analysis:
    ours = load_site(store, target_site)
    theirs = load_site(store, competitor_site) if competitor_site != target_site else []
    pages = ours + theirs
    index = {p.url: i for i, p in enumerate(pages)}
    resolve = graph.resolver(pages)

    anchors: Dict[int, List[str]] = {}
    for page in pages:
        for target_url, anchor, in_content in page.links:
            target = index.get(resolve(target_url))
            if in_content and anchor and target is not None:
                anchors.setdefault(target, []).append(anchor)

    rows = [i for i, p in enumerate(pages) if p.indexable and p.tokens]
    row_of = {page: row for row, page in enumerate(rows)}
    docs = [topics.weighted_tokens(pages[i], anchors.get(i, ())) for i in rows]
    vectors, top_terms, idf = topics.build_vectors(docs)
    labels = topics.cluster(vectors, seed)
    intents = [topics.intent_of(p, anchors.get(i, ())) for i, p in enumerate(pages)]
    shingle_sets = similar.page_shingles(pages)

    count = len(ours)
    weighted, every = graph.build_edges(ours, index, resolve)
    rank = graph.pagerank(count, weighted)
    home = index.get(resolve(start))
    depth = graph.click_depth(count, every, home if home is not None and home < count else None)
    inlinks = [0] * len(pages)
    for (_source, target), weight in weighted.items():
        if weight > 0:
            inlinks[target] += 1
    depth_all = depth + [-1] * len(theirs)

    a = Analysis(
        target_site=target_site, competitor_site=competitor_site, pages=pages, index=index,
        target_count=count, rows=rows, row_of=row_of, vectors=vectors, labels=labels,
        top_terms=top_terms, idf=idf, intents=intents, shingle_sets=shingle_sets,
        anchors=anchors, edges=weighted, rank=rank, depth=depth_all, inlinks=inlinks,
        resolve=resolve,
    )
    a.near_duplicates = similar.near_duplicates(ours, shingle_sets[:count], seed)

    anchor_tokens = [
        {t for text in anchors.get(i, ()) for t in tokenize(text)} for i in range(len(pages))
    ]
    our_rows = [row for row, page in enumerate(rows) if page < count]
    a.groups, a.healthy = topics.find_cannibalization(
        pages, [rows[r] for r in our_rows], vectors[our_rows], labels[our_rows],
        intents, shingle_sets, inlinks, depth_all, anchor_tokens,
    )
    a.gaps = topics.find_gaps(pages, rows, labels, top_terms, target_site)

    if priority_urls:
        wanted = (index.get(resolve(normalize(u) or "")) for u in priority_urls)
        a.priority = sorted({i for i in wanted if i is not None and i < count})
    else:
        a.priority = _default_priority(a)
    candidates = graph.link_candidates(pages, a.priority, row_of, vectors, weighted, idf)
    a.new_links, new_edges = graph.choose_links(
        count, weighted, candidates, [p.url for p in ours], budget
    )
    a.rank_after = graph.pagerank(count, new_edges)
    return a
