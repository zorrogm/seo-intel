import numpy as np

from seo_intel import config
from seo_intel.graph import LinkOptimiser, click_depth, pagerank


def test_pagerank_sums_to_one_and_ranks_hub_first():
    edges = {(1, 0): 1.0, (2, 0): 1.0, (3, 0): 1.0, (0, 1): 1.0}
    rank = pagerank(5, edges)
    assert abs(rank.sum() - 1.0) < 1e-9
    assert rank.argmax() == 0
    assert rank[4] == rank.min()


def test_click_depth():
    edges = {(0, 1): 1.0, (1, 2): 1.0, (0, 3): 1.0}
    assert click_depth(5, edges, 0) == [0, 1, 2, 1, -1]


def random_case(seed, nodes=14, links=30, candidates=10):
    rng = np.random.RandomState(seed)
    edges = {}
    while len(edges) < links:
        a, b = rng.randint(0, nodes, size=2)
        if a != b:
            edges[(int(a), int(b))] = 1.0
    priority = [0, 1]
    pool = []
    while len(pool) < candidates:
        source, target = int(rng.randint(2, nodes)), int(rng.choice(priority))
        link = {"source": source, "target": target}
        if (source, target) not in edges and link not in pool:
            pool.append(link)
    urls = [f"u{i:02d}" for i in range(nodes)]
    return nodes, edges, pool, priority, urls


def test_greedy_with_swaps_is_close_to_brute_force():
    worst = 1.0
    for seed in range(12):
        nodes, edges, pool, priority, urls = random_case(seed)
        optimiser = LinkOptimiser(nodes, edges, pool, priority, urls, budget=3)
        best = optimiser.score(optimiser.brute_force())
        ours = optimiser.score(optimiser.improve_by_swaps(optimiser.greedy()))
        assert ours <= best + 1e-12
        worst = min(worst, ours / best)
    assert worst > 0.97


def test_source_page_limit_is_kept():
    nodes, edges, pool, priority, urls = random_case(3, candidates=12)
    optimiser = LinkOptimiser(nodes, edges, pool, priority, urls, budget=10)
    chosen = optimiser.improve_by_swaps(optimiser.greedy())
    per_source = {}
    for source, _target in chosen:
        per_source[source] = per_source.get(source, 0) + 1
    assert max(per_source.values()) <= config.MAX_NEW_LINKS_PER_SOURCE
