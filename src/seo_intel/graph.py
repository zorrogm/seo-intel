"""Internal link graph, PageRank and the link optimiser."""
from __future__ import annotations

from collections import Counter, deque
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from seo_intel import config
from seo_intel.corpus import Page
from seo_intel.text import token_spans, tokenize
from seo_intel.topics import dot

Edges = Dict[Tuple[int, int], float]


def resolver(pages: List[Page]):
    """Follow stored redirects to the final URL."""
    hops = {p.url: p.redirect_to for p in pages if p.redirect_to}

    def resolve(url: str) -> str:
        seen = set()
        while url in hops and url not in seen:
            seen.add(url)
            url = hops[url]
        return url

    return resolve


def build_edges(pages: List[Page], index: Dict[str, int], resolve) -> Tuple[Edges, Edges]:
    """Weighted content edges, and every edge for depth."""
    weighted: Edges = {}
    every: Edges = {}
    for source, page in enumerate(pages):
        for target_url, _anchor, in_content in page.links:
            target = index.get(resolve(target_url))
            if target is None or target == source:
                continue
            every[(source, target)] = 1.0
            weight = config.CONTENT_LINK_WEIGHT if in_content else config.NAV_LINK_WEIGHT
            if weight > weighted.get((source, target), 0.0):
                weighted[(source, target)] = weight
    return weighted, every


def pagerank(count: int, edges: Edges) -> np.ndarray:
    if count == 0:
        return np.zeros(0)
    keys = sorted(edges)
    src = np.array([k[0] for k in keys], dtype=np.int64)
    dst = np.array([k[1] for k in keys], dtype=np.int64)
    weight = np.array([edges[k] for k in keys], dtype=np.float64)
    out = np.bincount(src, weights=weight, minlength=count)
    share = weight / out[src] if len(keys) else weight
    dangling = out == 0
    damping = config.PAGERANK_DAMPING
    rank = np.full(count, 1.0 / count)
    for _round in range(config.PAGERANK_ROUNDS):
        flow = np.bincount(dst, weights=rank[src] * share, minlength=count)
        new_rank = (1 - damping) / count + damping * (flow + rank[dangling].sum() / count)
        change = np.abs(new_rank - rank).sum()
        rank = new_rank
        if change < config.PAGERANK_TOLERANCE:
            break
    return rank


def click_depth(count: int, edges: Edges, home: Optional[int]) -> List[int]:
    """Clicks from the homepage, minus one if unreachable."""
    depth = [-1] * count
    if home is None:
        return depth
    neighbours: Dict[int, List[int]] = {}
    for source, target in sorted(edges):
        neighbours.setdefault(source, []).append(target)
    depth[home] = 0
    queue = deque([home])
    while queue:
        node = queue.popleft()
        for nxt in neighbours.get(node, ()):
            if depth[nxt] < 0:
                depth[nxt] = depth[node] + 1
                queue.append(nxt)
    return depth


def find_anchor(source: Page, target: Page, idf: Dict[str, float]):
    """A sentence on source that already names target."""
    name = tokenize(target.h1 or target.title)
    phrases = {}
    for size in range(config.ANCHOR_MIN_TOKENS, config.ANCHOR_MAX_TOKENS + 1):
        for start in range(len(name) - size + 1):
            phrase = tuple(name[start : start + size])
            score = sum(idf.get(token, 0.0) for token in phrase)
            if score > 0:
                phrases[phrase] = score
    best = None
    for sentence in source.sentences:
        spans = token_spans(sentence)
        if not config.SENTENCE_MIN_TOKENS <= len(spans) <= config.SENTENCE_MAX_TOKENS:
            continue
        words = [s[0] for s in spans]
        for size in range(config.ANCHOR_MAX_TOKENS, config.ANCHOR_MIN_TOKENS - 1, -1):
            for start in range(len(words) - size + 1):
                score = phrases.get(tuple(words[start : start + size]))
                if score and (best is None or score > best[0]):
                    anchor = sentence[spans[start][1] : spans[start + size - 1][2]]
                    best = (score, sentence, anchor)
    return (best[1], best[2]) if best else None


def link_candidates(pages: List[Page], priority: Sequence[int], row_of: Dict[int, int],
                    vectors: np.ndarray, edges: Edges, idf: Dict[str, float]) -> List[Dict]:
    """Relevant source pages with a ready anchor sentence."""
    page_of_row = {row: page for page, row in row_of.items()}
    candidates = []
    for target in priority:
        if target not in row_of:
            continue
        scores = dot(vectors, vectors[row_of[target]])
        order = np.lexsort((np.arange(len(scores)), -scores))
        picked = 0
        for row in order:
            if scores[row] < config.LINK_MIN_RELEVANCE or picked >= config.LINK_SOURCES_PER_TARGET:
                break
            source = page_of_row.get(int(row))
            if source is None or source == target or (source, target) in edges:
                continue
            found = find_anchor(pages[source], pages[target], idf)
            if not found:
                continue
            picked += 1
            candidates.append({
                "source": source,
                "target": target,
                "sentence": found[0],
                "anchor": found[1],
                "relevance": float(scores[row]),
            })
    return candidates


def choose_links(count: int, edges: Edges, candidates: List[Dict],
                 urls: List[str], budget: int) -> Tuple[List[Dict], Edges]:
    """Greedy: add the link sending most rank."""
    edges = dict(edges)
    chosen = []
    used = Counter()
    remaining = list(candidates)
    weight = config.CONTENT_LINK_WEIGHT
    while remaining and len(chosen) < budget:
        rank = pagerank(count, edges)
        out = np.zeros(count)
        for (source, _target), w in edges.items():
            out[source] += w
        best = None
        for candidate in remaining:
            source = candidate["source"]
            if used[source] >= config.MAX_NEW_LINKS_PER_SOURCE:
                continue
            gain = rank[source] * weight / (out[source] + weight)
            key = (-gain, urls[source], urls[candidate["target"]])
            if best is None or key < best[0]:
                best = (key, candidate)
        if best is None:
            break
        pick = best[1]
        edges[(pick["source"], pick["target"])] = weight
        used[pick["source"]] += 1
        chosen.append(pick)
        remaining = [c for c in remaining
                     if (c["source"], c["target"]) != (pick["source"], pick["target"])]
    return chosen, edges
