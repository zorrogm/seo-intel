"""Recall of near duplicate detection on planted pairs."""
import json
import sys
import time

import numpy as np

from seo_intel import config
from seo_intel.corpus import Page
from seo_intel.similar import near_duplicates, page_shingles
from seo_intel.text import jaccard

PAGES = 50000
PLANTED = 200
WORDS_PER_PAGE = 300
VOCABULARY = 5000


def make_vocabulary(rng):
    latin = ["w" + "".join(rng.choice(list("abcdefghijklmnop"), size=5)) for _ in range(VOCABULARY - 500)]
    hindi = ["श" + "".join(rng.choice(list("कखगघचछजझटठ"), size=3)) for _ in range(500)]
    return [str(word) for word in latin + hindi]


def main():
    rng = np.random.RandomState(0)
    vocabulary = make_vocabulary(rng)
    pages = []
    for number in range(PAGES - PLANTED):
        tokens = [vocabulary[i] for i in rng.randint(0, VOCABULARY, size=WORDS_PER_PAGE)]
        pages.append(Page(url=f"http://site.test/{number:06d}", site="s", status=200, tokens=tokens))
    planted = []
    for number in range(PLANTED):
        source = pages[number]
        tokens = list(source.tokens)
        # Change one to two percent of words
        for spot in rng.choice(len(tokens), size=rng.randint(3, 7), replace=False):
            tokens[spot] = vocabulary[rng.randint(0, VOCABULARY)]
        copy = Page(url=f"http://site.test/copy-{number:04d}", site="s", status=200, tokens=tokens)
        pages.append(copy)
        planted.append((source.url, copy.url))

    started = time.perf_counter()
    sets = page_shingles(pages)
    found = near_duplicates(pages, sets, seed=0)
    seconds = time.perf_counter() - started

    index = {p.url: i for i, p in enumerate(pages)}
    above = [(a, b) for a, b in planted
             if jaccard(sets[index[a]], sets[index[b]]) >= config.NEAR_DUPLICATE_OVERLAP]
    found_pairs = {(row["url_a"], row["url_b"]) for row in found}
    found_pairs |= {(b, a) for a, b in found_pairs}
    hits = sum(pair in found_pairs for pair in above)
    json.dump({
        "pages": PAGES,
        "all_pairs": PAGES * (PAGES - 1) // 2,
        "planted_pairs": PLANTED,
        "planted_pairs_above_threshold": len(above),
        "found": hits,
        "recall": round(hits / len(above), 4),
        "false_pairs_reported": len(found) - hits,
        "seconds": round(seconds, 1),
    }, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
