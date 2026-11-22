"""Topic vectors, intent, cannibalization and competitor gaps."""
from __future__ import annotations

import math
import re
import zlib
from collections import Counter
from typing import Dict, List, Sequence, Set, Tuple
from urllib.parse import urlsplit

import numpy as np

from seo_intel import config
from seo_intel.corpus import Page
from seo_intel.text import jaccard, set_overlap, tokenize

_PAGE_PARAM = re.compile(r"([?&])(page|p|pg|paged)=\d+")
_PAGE_PATH = re.compile(r"/page/\d+/?$")


def dot(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Matrix product without spurious platform warnings."""
    with np.errstate(all="ignore"):
        return a @ b


def weighted_tokens(page: Page, anchors: Sequence[str]) -> Counter:
    """Title counts most, then heading, then body."""
    counts = Counter()
    for token in tokenize(page.title):
        counts[token] += 3
    for token in tokenize(page.h1):
        counts[token] += 2
    for anchor in anchors:
        counts.update(tokenize(anchor))
    counts.update(page.tokens[: config.MAX_TOKENS_PER_PAGE])
    return counts


def build_vectors(docs: List[Counter]):
    """Hashed TF-IDF vectors, top terms, IDF, exact terms."""
    total = len(docs)
    seen = Counter()
    for doc in docs:
        seen.update(doc.keys())
    idf = {}
    for token, count in seen.items():
        too_common = total >= 10 and count / total > config.COMMON_TOKEN_SHARE
        if len(token) > 1 and not too_common:
            idf[token] = math.log((total + 1) / (count + 1)) + 1

    size = config.VECTOR_DIMENSIONS
    slots: Dict[str, Tuple[int, float]] = {}
    vectors = np.zeros((total, size), dtype=np.float32)
    top_terms = []
    sparse: List[Dict[str, float]] = []
    for row, doc in enumerate(docs):
        weights = []
        for token, count in doc.items():
            if token not in idf:
                continue
            if token not in slots:
                code = zlib.crc32(token.encode("utf-8"))
                slots[token] = (code % size, 1.0 if (code // size) % 2 else -1.0)
            slot, sign = slots[token]
            weight = (1 + math.log(count)) * idf[token]
            vectors[row, slot] += sign * weight
            weights.append((-weight, token))
        weights.sort()
        top_terms.append([token for _w, token in weights[:8]])
        # Strongest terms, unit length, for exact checks
        kept = weights[: config.EXACT_TERMS_PER_PAGE]
        length = math.sqrt(sum(w * w for w, _t in kept)) or 1.0
        sparse.append({token: -w / length for w, token in kept})
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms, top_terms, idf, sparse


def head_vectors(pages: List[Page], rows: List[int], anchors, idf: Dict[str, float]):
    """Unit vectors from title, heading and anchors only."""
    heads = []
    for index in rows:
        page = pages[index]
        counts = Counter(tokenize(page.title)) + Counter(tokenize(page.h1))
        for anchor in anchors.get(index, ()):
            counts.update(tokenize(anchor))
        weights = {t: (1 + math.log(n)) * idf[t] for t, n in counts.items() if t in idf}
        length = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        heads.append({token: w / length for token, w in weights.items()})
    return heads


def head_candidates(heads: List[Dict[str, float]]) -> List[Tuple[int, int]]:
    """Row pairs sharing rare title terms, via an index."""
    by_term: Dict[str, List[int]] = {}
    for row, head in enumerate(heads):
        for token in head:
            by_term.setdefault(token, []).append(row)
    shared = Counter()
    for token in sorted(by_term):
        members = by_term[token]
        # Common title words would pair everything
        if 2 <= len(members) <= config.HEAD_TERM_MAX_PAGES:
            for i, a in enumerate(members):
                for b in members[i + 1 :]:
                    shared[(a, b)] += 1
    return sorted(pair for pair, n in shared.items() if n >= config.HEAD_MIN_SHARED_TERMS)


def pair_similarity(a: int, b: int, sparse, heads) -> float:
    """Best of body match and title match."""
    body = exact_similarity(sparse[a], sparse[b])
    head = exact_similarity(heads[a], heads[b])
    return max(body, head if head >= config.HEAD_MIN_SIMILARITY else 0.0)


def exact_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Cosine over real terms, no hashing noise."""
    if len(a) > len(b):
        a, b = b, a
    return sum(weight * b[token] for token, weight in a.items() if token in b)


def cluster(vectors: np.ndarray, seed: int) -> np.ndarray:
    """Seeded spherical k-means, returns a topic per row."""
    count = len(vectors)
    k = max(1, min(config.MAX_TOPICS, int(math.sqrt(count / 2))))
    if count == 0:
        return np.zeros(0, dtype=np.int64)
    rng = np.random.RandomState(seed)
    centres = vectors[np.sort(rng.choice(count, size=k, replace=False))].copy()
    labels = np.full(count, -1, dtype=np.int64)
    for _round in range(config.KMEANS_ROUNDS):
        new_labels = np.argmax(dot(vectors, centres.T), axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for topic in range(k):
            members = vectors[labels == topic]
            if len(members):
                centre = members.sum(axis=0)
                norm = np.linalg.norm(centre)
                centres[topic] = centre / norm if norm else centre
    return labels


def _without_page_number(url: str) -> str:
    url = _PAGE_PATH.sub("/", url)
    return _PAGE_PARAM.sub(r"\1", url).rstrip("?&/")


def healthy_reason(a: Page, b: Page) -> str:
    """Why two similar pages are fine together."""
    if a.lang and b.lang and a.lang != b.lang:
        return "language versions"
    if b.url in a.hreflang or a.url in b.hreflang:
        return "language versions"
    if _without_page_number(a.url) == _without_page_number(b.url):
        return "paginated series"
    path_a, path_b = urlsplit(a.url).path.rstrip("/") + "/", urlsplit(b.url).path.rstrip("/") + "/"
    if path_a != path_b and (path_a.startswith(path_b) or path_b.startswith(path_a)):
        return "parent and child"
    return ""


def severity(parts: Dict[str, float]) -> float:
    return sum(config.SEVERITY_WEIGHTS[name] * value for name, value in parts.items())


def pair_signals(a: int, b: int, similarity: float, shingle_sets, inlinks, depth,
                 anchor_tokens) -> Dict[str, float]:
    links_a, links_b = inlinks[a], inlinks[b]
    both = links_a + links_b
    known_depth = depth[a] >= 0 and depth[b] >= 0
    return {
        "content_overlap": jaccard(shingle_sets[a], shingle_sets[b]),
        "topic_similarity": float(similarity),
        "link_split": 1 - abs(links_a - links_b) / both if both else 0.0,
        "anchor_conflict": set_overlap(anchor_tokens[a], anchor_tokens[b]),
        "depth_closeness": 1 / (1 + abs(depth[a] - depth[b])) if known_depth else 0.0,
    }


def _tight(pairs: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Drop members tied to few others in the group."""
    members = {i for pair in pairs for i in pair}
    ties = Counter(i for pair in pairs for i in pair)
    needed = config.GROUP_MIN_LINK_SHARE * (len(members) - 1)
    loose = {i for i in members if ties[i] < needed}
    return [pair for pair in pairs if pair[0] not in loose and pair[1] not in loose]


def find_cannibalization(pages: List[Page], rows: List[int], vectors: np.ndarray,
                         labels: np.ndarray, intents: List[str], shingle_sets,
                         inlinks, depth, anchor_tokens, sparse, heads) -> Tuple[List[Dict], List[Dict]]:
    """Groups of pages competing for one intent."""
    by_topic: Dict[int, List[int]] = {}
    for row, page_index in enumerate(rows):
        by_topic.setdefault(int(labels[row]), []).append(row)

    # Channel one: close in the shared topic space
    candidates = set()
    cap = config.CLUSTER_PAIR_CAP
    for topic in sorted(by_topic):
        members = by_topic[topic]
        # Big topics are compared in fixed chunks
        for start in range(0, len(members), cap):
            chunk = members[start : start + cap]
            sims = dot(vectors[chunk], vectors[chunk].T)
            close = np.argwhere(np.triu(sims >= config.CANNIBAL_MIN_SIMILARITY, k=1))
            candidates.update((chunk[i], chunk[j]) for i, j in close)
    # Channel two: nearly the same title and anchors
    candidates.update(head_candidates(heads))

    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pair_info: Dict[Tuple[int, int], Dict] = {}
    healthy = []
    for row_a, row_b in sorted(candidates):
        a, b = rows[row_a], rows[row_b]
        if intents[a] != intents[b]:
            continue
        # Confirm on real terms before trusting it
        similarity = pair_similarity(row_a, row_b, sparse, heads)
        if similarity < config.CANNIBAL_MIN_SIMILARITY:
            continue
        reason = healthy_reason(pages[a], pages[b])
        if reason:
            healthy.append({"url_a": pages[a].url, "url_b": pages[b].url, "reason": reason})
            continue
        signals = pair_signals(a, b, similarity, shingle_sets, inlinks, depth, anchor_tokens)
        pair_info[(a, b)] = signals
        parent[find(a)] = find(b)

    grouped: Dict[int, List[Tuple[int, int]]] = {}
    for pair in pair_info:
        grouped.setdefault(find(pair[0]), []).append(pair)
    grouped = {key: _tight(pairs) for key, pairs in grouped.items()}
    grouped = {key: pairs for key, pairs in grouped.items() if pairs}

    groups = []
    digits = config.FLOAT_DIGITS
    for pairs in grouped.values():
        worst = max(pairs, key=lambda p: (severity(pair_info[p]), pages[p[0]].url, pages[p[1]].url))
        members = sorted({i for pair in pairs for i in pair}, key=lambda i: pages[i].url)
        keep = min(members, key=lambda i: (-inlinks[i], depth[i] if depth[i] >= 0 else 10**6, pages[i].url))
        groups.append({
            "urls": [pages[i].url for i in members],
            "intent": intents[members[0]],
            "severity": round(severity(pair_info[worst]), digits),
            "keep": pages[keep].url,
            "worst_pair": {
                "url_a": pages[worst[0]].url,
                "url_b": pages[worst[1]].url,
                "signals": {k: round(v, digits) for k, v in sorted(pair_info[worst].items())},
            },
        })
    groups.sort(key=lambda g: (-g["severity"], g["urls"]))
    healthy.sort(key=lambda h: (h["url_a"], h["url_b"]))
    return groups, healthy


def find_gaps(pages: List[Page], rows: List[int], labels: np.ndarray,
              top_terms: List[List[str]], target_site: str) -> List[Dict]:
    """Topics the competitor covers deeply and we barely do."""
    ours = [p for p in pages if p.site == target_site and p.indexable]
    spoken = Counter(p.lang for p in ours if p.lang)
    known = {lang for lang, n in spoken.items() if n >= config.LANGUAGE_MIN_SHARE * len(ours)}
    topics: Dict[int, Dict] = {}
    for row, page_index in enumerate(rows):
        page = pages[page_index]
        # Skip competitor pages in languages we lack
        if page.site != target_site and known and page.lang and page.lang not in known:
            continue
        topic = topics.setdefault(int(labels[row]), {"ours": [], "theirs": [], "terms": Counter()})
        topic["ours" if page.site == target_site else "theirs"].append(page)
        if page.site != target_site:
            topic["terms"].update(top_terms[row])

    gaps = []
    for topic_id in sorted(topics):
        topic = topics[topic_id]
        their_words = sum(p.word_count for p in topic["theirs"])
        our_words = sum(p.word_count for p in topic["ours"])
        if len(topic["theirs"]) < config.GAP_MIN_PAGES or their_words < config.GAP_MIN_WORDS:
            continue
        if our_words > config.GAP_MAX_TARGET_SHARE * their_words:
            continue
        terms = sorted(topic["terms"].items(), key=lambda item: (-item[1], item[0]))
        examples = sorted(topic["theirs"], key=lambda p: (-p.word_count, p.url))[:3]
        gaps.append({
            "topic": [term for term, _n in terms[: config.TOPIC_LABEL_TERMS]],
            "competitor_pages": len(topic["theirs"]),
            "competitor_words": their_words,
            "target_pages": len(topic["ours"]),
            "target_words": our_words,
            "examples": [p.url for p in examples],
        })
    gaps.sort(key=lambda g: (-g["competitor_words"], g["examples"]))
    return gaps
