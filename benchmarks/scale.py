"""Time and memory of the analysis stages at crawl size."""
import json
import resource
import sys
import time

import numpy as np

from seo_intel import analysis
from seo_intel.corpus import Page

PAGES_PER_SITE = int(sys.argv[1]) if len(sys.argv) > 1 else 10500
WORDS = 500
LINKS = 12
TOPICS = 400


def build_site(rng, site, vocabulary):
    base = f"http://{site}"
    urls = [base + "/"] + [f"{base}/t{n % TOPICS}/page-{n}" for n in range(1, PAGES_PER_SITE)]
    pages = []
    for number, url in enumerate(urls):
        topic = number % TOPICS
        # Topic words plus shared everyday words
        picks = np.concatenate([
            rng.randint(topic * 40, topic * 40 + 40, size=WORDS // 2),
            rng.zipf(1.3, size=WORDS // 2) % 3000 + TOPICS * 40,
        ])
        tokens = [vocabulary[i] for i in picks]
        sentences = [" ".join(tokens[i : i + 20]) + "." for i in range(0, WORDS, 20)]
        title = " ".join(vocabulary[topic * 40 + i] for i in range(3)) + f" part {number}"
        page = Page(url=url, site=site, status=200, lang="en", title=title, h1=title,
                    tokens=tokens, sentences=sentences)
        for target in rng.randint(0, PAGES_PER_SITE, size=LINKS):
            anchor = " ".join(vocabulary[(int(target) % TOPICS) * 40 + i] for i in range(2))
            page.links.append((urls[int(target)], anchor, True))
        pages.append(page)
    pages.sort(key=lambda p: p.url)
    return pages


def main():
    rng = np.random.RandomState(0)
    vocabulary = [f"w{i}" for i in range(TOPICS * 40 + 3000)]
    ours = build_site(rng, "ours.test", vocabulary)
    theirs = build_site(rng, "theirs.test", vocabulary)
    started = time.perf_counter()
    result = analysis.analyse_pages(ours, theirs, "ours.test", "theirs.test",
                                    "http://ours.test/", 0, None, 40)
    seconds = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux kilobytes
    peak_mb = peak / 1e6 if sys.platform == "darwin" else peak / 1e3
    json.dump({
        "pages_total": len(ours) + len(theirs),
        "internal_links": len(result.edges),
        "analysis_seconds": round(seconds, 1),
        "peak_ram_mb": round(peak_mb),
        "cannibalization_groups": len(result.groups),
        "gaps": len(result.gaps),
        "new_links": len(result.new_links),
    }, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
