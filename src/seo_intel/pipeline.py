"""The whole run: crawl, analyse, plan, write."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional

from seo_intel import config
from seo_intel.agent import run_agent
from seo_intel.analysis import analyse
from seo_intel.crawl import crawl_sites
from seo_intel.facts import Facts
from seo_intel.llm import Gemini
from seo_intel.plan import build_candidates, finalise
from seo_intel.report import write_json, write_outputs
from seo_intel.store import Store
from seo_intel.urls import site_key


def run(domain: str, competitor: str, folder: Path, seed: int = config.DEFAULT_SEED,
        crawl_minutes: float = config.CRAWL_MINUTES, max_urls: int = config.MAX_URLS_PER_SITE,
        priority_urls: Optional[List[str]] = None, link_budget: int = config.LINK_BUDGET,
        gap_seconds: float = config.REQUEST_GAP_SECONDS, use_llm: bool = True) -> Dict:
    asyncio.run(crawl_sites([domain, competitor], folder, crawl_minutes, max_urls, gap_seconds))

    store = Store(folder / config.CRAWL_DB_NAME, max_urls)
    try:
        start = store.get_meta("start:" + domain) or ""
        competitor_start = store.get_meta("start:" + competitor) or ""
        analysis = analyse(
            store, site_key(start), site_key(competitor_start), start,
            seed, priority_urls, link_budget,
        )
        facts = Facts(analysis, store)
        candidates = build_candidates(analysis, facts)
        llm = Gemini(folder / config.LLM_CACHE_FOLDER, seed)
        picks = run_agent(candidates, facts, llm) if use_llm else None
        plan = finalise(candidates, picks or [], facts)
        write_outputs(folder, analysis, plan)
    finally:
        store.close()

    logs = folder / config.LOG_FOLDER
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "rejections.jsonl", "w", encoding="utf-8") as handle:
        for rejection in plan["rejections"]:
            handle.write(json.dumps(rejection, sort_keys=True, ensure_ascii=False) + "\n")
    usage = dict(llm.usage(), plan_written_by="agent" if picks else "fallback")
    write_json(logs / "llm_usage.json", usage)
    return {
        "pages": len(analysis.pages),
        "candidates": len(candidates),
        "actions": len(plan["actions"]),
        "rejections": len(plan["rejections"]),
        "llm": usage,
    }
