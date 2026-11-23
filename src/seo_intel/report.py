"""Write output files the same way every time."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from seo_intel import config
from seo_intel import issues
from seo_intel.analysis import Analysis
from seo_intel.plan import claim_text
from seo_intel.render import render_report
from seo_intel.store import Store


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1)
    path.write_text(text + "\n", encoding="utf-8")


def crawl_summary(a: Analysis) -> Dict:
    summary = {}
    for site in sorted({a.target_site, a.competitor_site}):
        pages = [p for p in a.pages if p.site == site]
        statuses: Dict[str, int] = {}
        for page in pages:
            statuses[str(page.status)] = statuses.get(str(page.status), 0) + 1
        summary[site] = {
            "pages_fetched": len(pages),
            "indexable": sum(p.indexable for p in pages),
            "soft_404": sum(bool(p.soft_404) for p in pages),
            "by_status": statuses,
        }
    return summary


def link_report(a: Analysis) -> Dict:
    digits = 8
    priority = [
        {
            "url": a.pages[i].url,
            "pagerank_before": round(float(a.rank[i]), digits),
            "pagerank_after": round(float(a.rank_after[i]), digits),
        }
        for i in a.priority
    ]
    links = [
        {
            "source": a.pages[l["source"]].url,
            "target": a.pages[l["target"]].url,
            "sentence": l["sentence"],
            "anchor": l["anchor"],
            "relevance": round(l["relevance"], config.FLOAT_DIGITS),
        }
        for l in a.new_links
    ]
    return {
        "priority_pages": priority,
        "priority_pagerank_before": round(sum(p["pagerank_before"] for p in priority), digits),
        "priority_pagerank_after": round(sum(p["pagerank_after"] for p in priority), digits),
        "new_links": links,
    }


def _claim_line(claim: Dict) -> str:
    return f"- `{claim['id']}` {claim_text(claim, 300)}"


def plan_markdown(actions: List[Dict]) -> str:
    lines = ["# Action plan", ""]
    for action in actions:
        lines.append(f"## {action['rank']}. {action['type'].replace('_', ' ')}")
        lines.append("")
        lines.append(action["rationale"])
        lines.append("")
        lines.append("Pages:")
        lines.extend(f"- {url}" for url in action["urls"])
        lines.append("")
        lines.append("Verified claims:")
        lines.extend(_claim_line(c) for c in action["claims"])
        lines.append("")
    return "\n".join(lines)


def write_outputs(folder: Path, a: Analysis, plan: Dict, store: Store) -> None:
    out = folder / config.OUTPUT_FOLDER
    write_json(out / "crawl_summary.json", crawl_summary(a))
    write_json(out / "crawl_issues.json", issues.crawl_issues(a))
    write_json(out / "spider_traps.json", issues.trap_report(a, store))
    write_json(out / "soft_404s.json", issues.soft_404s(a))
    write_json(out / "change_report.json", issues.change_report(store))
    write_json(out / "render_report.json",
               render_report(store, [a.target_site, a.competitor_site]))
    write_json(out / "near_duplicates.json", a.near_duplicates)
    write_json(out / "cannibalization.json", {"groups": a.groups, "healthy_pairs": a.healthy})
    write_json(out / "gaps.json", a.gaps)
    write_json(out / "internal_links.json", link_report(a))
    write_json(out / "action_plan.json", plan["actions"])
    (out / "action_plan.md").write_text(plan_markdown(plan["actions"]), encoding="utf-8")
