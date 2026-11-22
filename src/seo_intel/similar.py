"""Near duplicate pages without comparing every pair."""
from __future__ import annotations

from typing import Dict, List, Set

import numpy as np

from seo_intel import config
from seo_intel.corpus import Page
from seo_intel.text import MinHasher, jaccard, shingles


def page_shingles(pages: List[Page]) -> List[Set[int]]:
    return [shingles(p.tokens) for p in pages]


def near_duplicates(pages: List[Page], shingle_sets: List[Set[int]], seed: int) -> List[Dict]:
    """Pairs of pages with very high text overlap."""
    hasher = MinHasher(seed)
    rows = config.MINHASH_PERMUTATIONS // config.LSH_BANDS
    buckets: Dict[tuple, List[int]] = {}
    for index, page in enumerate(pages):
        if len(page.tokens) < config.MIN_TOKENS_FOR_DUPLICATES or not shingle_sets[index]:
            continue
        signature = hasher.signature(shingle_sets[index])
        for band in range(config.LSH_BANDS):
            key = (band, signature[band * rows : (band + 1) * rows].tobytes())
            buckets.setdefault(key, []).append(index)

    candidates = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        if len(members) > config.LSH_BUCKET_CAP:
            # Huge bucket: compare everyone to the first
            candidates.update((members[0], other) for other in members[1:])
            continue
        for i, a in enumerate(members):
            candidates.update((a, b) for b in members[i + 1 :])

    pairs = []
    for a, b in sorted(candidates):
        overlap = jaccard(shingle_sets[a], shingle_sets[b])
        if overlap >= config.NEAR_DUPLICATE_OVERLAP:
            pairs.append({
                "url_a": pages[a].url,
                "url_b": pages[b].url,
                "content_overlap": round(overlap, config.FLOAT_DIGITS),
            })
    return pairs
