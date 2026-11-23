"""Ablation: what each signal adds to cannibalization precision.

Runs on a generated site with known groups.
"""
import json
import sys

import numpy as np

from seo_intel import analysis, intent, topics
from seo_intel.corpus import Page

SITE = "site.test"
BASE = "http://site.test"
TOPICS = 60
SINGLE_PAGES = 250
CHROME_WORDS = [f"chrome{i}" for i in range(40)]
CHROME_SIZE = 500
SLUGS = ["overview", "handbook", "explained"]
# Half the groups say little about their topic
THIN_TOPIC_WORDS = 12
RICH_TOPIC_WORDS = 220


def words(rng, pool, count):
    return [pool[i] for i in rng.randint(0, len(pool), size=count)]


def build(rng, use_titles=True, use_anchors=True, strip_template=True):
    common = [f"common{i}" for i in range(300)]
    pages, truth = [], {}

    def add(path, title, topic_words, group=None, lang="en", extra_title="", thin=False):
        size = THIN_TOPIC_WORDS if thin else RICH_TOPIC_WORDS
        tokens = words(rng, topic_words, size) + words(rng, common, 340 - size)
        rng.shuffle(tokens)
        if not strip_template:
            tokens = words(rng, CHROME_WORDS, CHROME_SIZE) + tokens
        text = " ".join(tokens)
        page = Page(url=BASE + path, site=SITE, status=200, lang=lang,
                    title=(title + extra_title) if use_titles else "",
                    h1=title if use_titles else "",
                    tokens=tokens, sentences=[text])
        pages.append(page)
        if group is not None:
            truth[page.url] = group
        return page

    home = add("/", "Welcome", common)
    for topic in range(TOPICS):
        pool = [f"t{topic}w{i}" for i in range(25)]
        head = " ".join(pool[:3])
        kind = topic % 6
        if kind in (0, 1, 2):
            # Real cannibals: same topic, same intent
            # Different slugs, since numbered URLs mean a series
            made = [add(f"/guides/{topic}/{slug}", f"{head} guide", pool, group=topic,
                        thin=topic % 4 < 2)
                    for slug in SLUGS[: 2 + topic % 2]]
        elif kind == 3:
            # Different intent, should not be grouped
            made = [add(f"/guides/{topic}", f"{head} guide", pool),
                    add(f"/shop/{topic}", f"buy {head} price", pool)]
        elif kind == 4:
            # Healthy: paginated series and child page
            made = [add(f"/list/{topic}", f"{head} list", pool),
                    add(f"/list/{topic}?page=2", f"{head} list", pool),
                    add(f"/list/{topic}/faq", f"{head} list", pool)]
        else:
            # Healthy: language versions of one page
            made = [add(f"/en/{topic}", f"{head} guide", pool, lang="en"),
                    add(f"/hi/{topic}", f"{head} guide", pool, lang="hi")]
            made[0].hreflang = [made[1].url]
            made[1].hreflang = [made[0].url]
        for page in made:
            anchor = head if use_anchors else ""
            home.links.append((page.url, anchor, True))
    for number in range(SINGLE_PAGES):
        pool = [f"s{number}w{i}" for i in range(25)]
        page = add(f"/notes/{number}", " ".join(pool[:3]), pool)
        home.links.append((page.url, " ".join(pool[:3]) if use_anchors else "", True))
    pages.sort(key=lambda p: p.url)
    return pages, truth


def measure(name, rng_seed=0, patch=None, **toggles):
    rng = np.random.RandomState(rng_seed)
    pages, truth = build(rng, **toggles)
    saved = {}
    for target, attribute, value in patch or []:
        saved[(target, attribute)] = getattr(target, attribute)
        setattr(target, attribute, value)
    try:
        result = analysis.analyse_pages(pages, [], SITE, SITE, BASE + "/", 0, None, 0)
    finally:
        for (target, attribute), value in saved.items():
            setattr(target, attribute, value)
    planted = set(truth.values())
    top = result.groups[:20]
    correct = sum(len({truth.get(u, -1 - i) for i, u in enumerate(g["urls"])}) == 1
                  and g["urls"][0] in truth for g in top)
    found = {truth[g["urls"][0]] for g in result.groups
             if all(u in truth for u in g["urls"]) and len({truth[u] for u in g["urls"]}) == 1}
    clean = sum(all(u in truth for u in g["urls"]) and len({truth[u] for u in g["urls"]}) == 1
                for g in result.groups)
    return {
        "setup": name,
        "groups_reported": len(result.groups),
        "precision_all_groups": round(clean / max(1, len(result.groups)), 3),
        "precision_at_20": round(correct / max(1, len(top)), 3),
        "recall_of_planted_groups": round(len(found) / len(planted), 3),
    }


def main():
    rows = [
        measure("all signals"),
        measure("no title or heading", use_titles=False),
        measure("no anchor text", use_anchors=False),
        measure("no title, heading or anchors", use_titles=False, use_anchors=False),
        measure("no template removal", strip_template=False),
        measure("no intent check",
                patch=[(intent, "rule_intent", lambda page, anchors: ("informational", False))]),
        measure("no healthy pair rules", patch=[(topics, "healthy_reason", lambda a, b, overlap=0.0: "")]),
    ]
    json.dump(rows, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
