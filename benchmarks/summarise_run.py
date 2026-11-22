"""Print the headline numbers of one run folder."""
import json
import sqlite3
import sys
from pathlib import Path

from seo_intel import config


def load(folder: Path, name: str):
    return json.loads((folder / config.OUTPUT_FOLDER / name).read_text(encoding="utf-8"))


def main():
    folder = Path(sys.argv[1])
    db = sqlite3.connect(str(folder / config.CRAWL_DB_NAME))
    sites = [row[0] for row in db.execute(
        "SELECT DISTINCT site FROM urls WHERE site NOT LIKE 'probe:%' ORDER BY site")]
    summary = {"folder": folder.name, "sites": {}}
    traps, renders = load(folder, "spider_traps.json"), load(folder, "render_report.json")
    crawl = load(folder, "crawl_summary.json")
    for site in sites:
        known = db.execute("SELECT COUNT(*) FROM urls WHERE site=?", (site,)).fetchone()[0]
        blocked = db.execute(
            "SELECT COUNT(*) FROM urls WHERE site=? AND state='blocked'", (site,)).fetchone()[0]
        rendered = renders["sites"].get(site, {})
        summary["sites"][site] = {
            "urls_known": known,
            "pages_fetched": crawl[site]["pages_fetched"],
            "indexable": crawl[site]["indexable"],
            "soft_404": crawl[site]["soft_404"],
            "blocked_by_robots": blocked,
            "trap_urls_refused": traps[site]["urls_blocked"],
            "trap_patterns": len(traps[site]["traps"]),
            "rendered_share": rendered.get("rendered_share"),
            "changed_by_rendering": rendered.get("changed_by_rendering"),
            "flagged_not_rendered": rendered.get("flagged_but_not_rendered"),
        }
    plan = load(folder, "action_plan.json")
    links = load(folder, "internal_links.json")
    kinds = {}
    for action in plan:
        kinds[action["type"]] = kinds.get(action["type"], 0) + 1
    summary.update({
        "cannibalization_groups": len(load(folder, "cannibalization.json")["groups"]),
        "gaps": len(load(folder, "gaps.json")),
        "near_duplicate_pairs": len(load(folder, "near_duplicates.json")),
        "new_links": len(links["new_links"]),
        "priority_pagerank_before": links["priority_pagerank_before"],
        "priority_pagerank_after": links["priority_pagerank_after"],
        "actions": kinds,
        "claims_in_plan": sum(len(a["claims"]) for a in plan),
        "llm": json.loads((folder / config.LOG_FOLDER / "llm_usage.json").read_text()),
        "rejections": sum(1 for _ in open(folder / config.LOG_FOLDER / "rejections.jsonl")),
    })
    json.dump(summary, sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
