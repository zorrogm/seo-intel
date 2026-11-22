"""Redirect, canonical and indexing problems found in the crawl."""
from __future__ import annotations

from typing import Dict, List

from seo_intel import config
from seo_intel.analysis import Analysis
from seo_intel.store import Store

_CHANGE_KINDS = ("new", "removed", "title_changed", "canonical_changed", "newly_redirected")


def _redirect_chains(pages) -> List[Dict]:
    hops = {p.url: (p.redirect_to, p.redirect_kind) for p in pages if p.redirect_to}
    targets = {target for target, _kind in hops.values()}
    chains = []
    for start in sorted(hops):
        in_loop = False
        urls, kinds, url = [start], [], start
        while url in hops:
            target, kind = hops[url]
            kinds.append(kind)
            if target in urls:
                in_loop = True
                break
            urls.append(target)
            url = target
        # Report from the first URL, loops from anywhere
        if start in targets and not in_loop:
            continue
        hidden = any(kind != "http" for kind in kinds)
        if len(kinds) >= 2 or in_loop or hidden:
            chains.append({"urls": urls, "kinds": kinds, "loop": in_loop})
    return chains


def _canonical_problems(a: Analysis, pages) -> List[Dict]:
    problems = []
    for page in pages:
        if page.status != 200 or page.canonical in ("", page.url):
            continue
        chain, url = [page.url], page.canonical
        while url in a.index and url not in chain and len(chain) < config.START_MAX_REDIRECTS:
            chain.append(url)
            nxt = a.pages[a.index[url]].canonical
            if nxt in ("", url):
                break
            url = nxt
        if page.canonical not in a.index:
            continue
        target = a.pages[a.index[page.canonical]]
        if len(chain) > 2:
            problems.append({"url": page.url, "problem": "canonical chain", "chain": chain})
        elif target.redirect_to:
            problems.append({"url": page.url, "problem": "canonical points to a redirect",
                             "chain": chain})
        elif target.status != 200:
            problems.append({"url": page.url, "problem": f"canonical points to a {target.status}",
                             "chain": chain})
    return problems


def crawl_issues(a: Analysis) -> Dict:
    pages = a.pages[: a.target_count]
    return {
        "redirect_chains": _redirect_chains(pages),
        "canonical_problems": _canonical_problems(a, pages),
        "noindex_by_header": sorted(p.url for p in pages if "noindex" in p.x_robots.lower()),
        "noindex_by_meta": sorted(p.url for p in pages if "noindex" in p.meta_robots),
    }


def soft_404s(a: Analysis) -> List[Dict]:
    return [{"url": p.url, "reason": p.soft_404} for p in a.pages if p.soft_404]


def trap_report(a: Analysis, store: Store) -> Dict:
    report = {}
    for site in sorted({a.target_site, a.competitor_site}):
        rows = store.traps(site)
        report[site] = {
            "urls_blocked": sum(row[3] for row in rows),
            "traps": [
                {"kind": kind, "pattern": pattern, "example": example, "blocked": blocked}
                for kind, pattern, example, blocked in rows
            ],
        }
    return report


def change_report(store: Store) -> Dict:
    """What changed since the previous crawl."""
    run = int(store.get_meta("runs") or 1)
    report: Dict = {"crawl_number": run, "sites": {}}
    for site, url, kind, old, new in store.changes(run):
        bucket = report["sites"].setdefault(site, {name: [] for name in _CHANGE_KINDS})
        entry = {"url": url}
        if kind.endswith("_changed"):
            entry.update(old=old, new=new)
        elif kind == "newly_redirected":
            entry.update(redirects_to=new)
        bucket[kind].append(entry)
    return report
