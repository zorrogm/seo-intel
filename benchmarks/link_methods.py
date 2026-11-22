"""Compare link picking methods against brute force."""
import json
import sys
import time

import numpy as np

from seo_intel.graph import LinkOptimiser

GRAPHS = 40
NODES = 30
LINKS = 90
CANDIDATES = 14
BUDGET = 4


def random_case(seed):
    rng = np.random.RandomState(seed)
    edges = {}
    while len(edges) < LINKS:
        a, b = rng.randint(0, NODES, size=2)
        if a != b:
            edges[(int(a), int(b))] = 1.0
    priority = [0, 1, 2]
    pool = []
    while len(pool) < CANDIDATES:
        link = {"source": int(rng.randint(3, NODES)), "target": int(rng.choice(priority))}
        if (link["source"], link["target"]) not in edges and link not in pool:
            pool.append(link)
    return edges, pool, priority


def main():
    urls = [f"u{i:03d}" for i in range(NODES)]
    methods = {
        "naive, ranked once": lambda o: o.naive(),
        "greedy on estimates": lambda o: o.greedy(shortlist=1),
        "greedy on exact gain": lambda o: o.greedy(),
        "greedy plus swaps": lambda o: o.improve_by_swaps(o.greedy()),
    }
    ratios = {name: [] for name in methods}
    seconds = {name: 0.0 for name in methods}
    for seed in range(GRAPHS):
        edges, pool, priority = random_case(seed)
        optimiser = LinkOptimiser(NODES, edges, pool, priority, urls, BUDGET)
        base = optimiser.score([])
        best = optimiser.score(optimiser.brute_force()) - base
        for name, method in methods.items():
            started = time.perf_counter()
            chosen = method(optimiser)
            seconds[name] += time.perf_counter() - started
            ratios[name].append((optimiser.score(chosen) - base) / best)
    rows = {
        name: {
            "mean_share_of_best_gain": round(float(np.mean(values)), 4),
            "worst_share_of_best_gain": round(float(np.min(values)), 4),
            "times_optimal": int(sum(v > 1 - 1e-9 for v in values)),
            "seconds": round(seconds[name], 2),
        }
        for name, values in ratios.items()
    }
    json.dump({"graphs": GRAPHS, "nodes": NODES, "budget": BUDGET,
               "candidates": CANDIDATES, "methods": rows}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
