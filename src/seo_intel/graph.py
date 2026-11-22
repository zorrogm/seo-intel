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


class RankGraph:
    """PageRank over fixed edges plus trial links."""

    def __init__(self, count: int, edges: Edges):
        keys = sorted(edges)
        self.count = count
        self.src = np.array([k[0] for k in keys], dtype=np.int64)
        self.dst = np.array([k[1] for k in keys], dtype=np.int64)
        self.weight = np.array([edges[k] for k in keys], dtype=np.float64)
        self.base = None

    def rank(self, extra: Sequence[Tuple[int, int]] = (), start=None) -> np.ndarray:
        count = self.count
        if count == 0:
            return np.zeros(0)
        src, dst, weight = self.src, self.dst, self.weight
        if extra:
            added = np.array(sorted(extra), dtype=np.int64).reshape(-1, 2)
            src = np.concatenate([src, added[:, 0]])
            dst = np.concatenate([dst, added[:, 1]])
            weight = np.concatenate([weight, np.full(len(added), config.CONTENT_LINK_WEIGHT)])
        out = np.bincount(src, weights=weight, minlength=count)
        share = weight / out[src] if len(src) else weight
        dangling = out == 0
        damping = config.PAGERANK_DAMPING
        rank = np.full(count, 1.0 / count) if start is None else start.copy()
        for _round in range(config.PAGERANK_ROUNDS):
            flow = np.bincount(dst, weights=rank[src] * share, minlength=count)
            new_rank = (1 - damping) / count + damping * (flow + rank[dangling].sum() / count)
            change = np.abs(new_rank - rank).sum()
            rank = new_rank
            if change < config.PAGERANK_TOLERANCE:
                break
        return rank

    def out_weight(self, extra: Sequence[Tuple[int, int]] = ()) -> np.ndarray:
        out = np.bincount(self.src, weights=self.weight, minlength=self.count)
        for source, _target in extra:
            out[source] += config.CONTENT_LINK_WEIGHT
        return out


def pagerank(count: int, edges: Edges) -> np.ndarray:
    return RankGraph(count, edges).rank()


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
                    vectors: np.ndarray, edges: Edges, idf: Dict[str, float],
                    own_pages: int) -> List[Dict]:
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
            # Links can only come from our own site
            if source is None or source >= own_pages or source == target:
                continue
            if (source, target) in edges:
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


Link = Tuple[int, int]


class LinkOptimiser:
    """Pick new links that lift priority pages most."""

    def __init__(self, count: int, edges: Edges, candidates: List[Dict],
                 priority: Sequence[int], urls: List[str], budget: int):
        self.graph = RankGraph(count, edges)
        self.links: List[Link] = sorted(
            {(c["source"], c["target"]) for c in candidates},
            key=lambda link: (urls[link[0]], urls[link[1]]),
        )
        self.priority = np.array(sorted(priority), dtype=np.int64)
        self.budget = budget
        self.base_rank = self.graph.rank()
        self.evaluations = 0

    def score(self, chosen: Sequence[Link], start=None) -> float:
        """Total PageRank of the priority pages."""
        self.evaluations += 1
        rank = self.graph.rank(chosen, self.base_rank if start is None else start)
        return float(rank[self.priority].sum())

    def allowed(self, chosen: Sequence[Link], link: Link) -> bool:
        if link in chosen:
            return False
        used = sum(1 for source, _t in chosen if source == link[0])
        return used < config.MAX_NEW_LINKS_PER_SOURCE

    def _estimates(self, chosen: Sequence[Link]) -> List[Tuple[float, int]]:
        """Cheap guess: rank the link would pass on."""
        rank = self.graph.rank(chosen, self.base_rank)
        out = self.graph.out_weight(chosen)
        weight = config.CONTENT_LINK_WEIGHT
        guesses = []
        for position, link in enumerate(self.links):
            if self.allowed(chosen, link):
                guesses.append((-rank[link[0]] * weight / (out[link[0]] + weight), position))
        guesses.sort()
        return guesses

    def naive(self) -> List[Link]:
        """Rank once on the original graph."""
        chosen: List[Link] = []
        for _guess, position in self._estimates([]):
            if len(chosen) < self.budget and self.allowed(chosen, self.links[position]):
                chosen.append(self.links[position])
        return chosen

    def greedy(self, shortlist: int = config.GREEDY_SHORTLIST) -> List[Link]:
        """Each step, test the best guesses exactly."""
        chosen: List[Link] = []
        while len(chosen) < self.budget:
            guesses = self._estimates(chosen)[:shortlist]
            if not guesses:
                break
            best = max(
                guesses,
                key=lambda g: (self.score(chosen + [self.links[g[1]]]), -g[1]),
            )
            chosen.append(self.links[best[1]])
        return chosen

    def improve_by_swaps(self, chosen: List[Link], rounds: int = config.SWAP_ROUNDS,
                         shortlist: int = config.SWAP_SHORTLIST) -> List[Link]:
        """Swap in a spare link when it scores higher."""
        chosen = list(chosen)
        best = self.score(chosen)
        for _round in range(rounds):
            improved = False
            for slot in range(len(chosen)):
                rest = chosen[:slot] + chosen[slot + 1 :]
                for _guess, position in self._estimates(rest)[:shortlist]:
                    trial = rest + [self.links[position]]
                    value = self.score(trial)
                    if value > best + 1e-12:
                        chosen, best, improved = trial, value, True
                        break
            if not improved:
                break
        return chosen

    def brute_force(self) -> List[Link]:
        """Try every combination, only for tiny inputs."""
        from itertools import combinations

        best, best_value = [], self.score([])
        size = min(self.budget, len(self.links))
        for combo in combinations(self.links, size):
            sources = Counter(source for source, _t in combo)
            if max(sources.values(), default=0) > config.MAX_NEW_LINKS_PER_SOURCE:
                continue
            value = self.score(combo)
            if value > best_value + 1e-15:
                best, best_value = list(combo), value
        return best


def choose_links(count: int, edges: Edges, candidates: List[Dict], priority: Sequence[int],
                 urls: List[str], budget: int) -> Tuple[List[Dict], np.ndarray]:
    """Chosen links and the PageRank after adding them."""
    optimiser = LinkOptimiser(count, edges, candidates, priority, urls, budget)
    chosen = optimiser.improve_by_swaps(optimiser.greedy())
    by_link = {(c["source"], c["target"]): c for c in candidates}
    picked = sorted(chosen, key=lambda link: (urls[link[1]], urls[link[0]]))
    # Proof: recompute from scratch on the new graph
    after = optimiser.graph.rank(chosen)
    return [by_link[link] for link in picked], after
