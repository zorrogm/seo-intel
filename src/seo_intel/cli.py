"""Command line entry point for seo-intel."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from seo_intel import config
from seo_intel import pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seo-intel")
    parser.add_argument("domain", help="site to analyse")
    parser.add_argument("--competitor", required=True, help="site to compare against")
    parser.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    parser.add_argument("--out", default=config.OUTPUT_DIR_NAME)
    parser.add_argument("--crawl-minutes", type=float, default=config.CRAWL_MINUTES)
    parser.add_argument("--max-urls", type=int, default=config.MAX_URLS_PER_SITE)
    parser.add_argument("--priority-urls", help="text file, one URL per line")
    parser.add_argument("--link-budget", type=int, default=config.LINK_BUDGET)
    parser.add_argument("--no-llm", action="store_true", help="skip the LLM agent")
    return parser


def run_dir(out: str, domain: str, competitor: str) -> Path:
    """One folder per site pair, reused on rerun."""
    slug = lambda text: re.sub(r"[^a-z0-9.-]+", "_", text.lower()).strip("_")
    return Path(out) / f"{slug(domain)}__{slug(competitor)}"


def main() -> int:
    args = build_parser().parse_args()
    folder = run_dir(args.out, args.domain, args.competitor)
    priority = None
    if args.priority_urls:
        lines = Path(args.priority_urls).read_text(encoding="utf-8").splitlines()
        priority = [line.strip() for line in lines if line.strip()]
    print(f"Running {args.domain} against {args.competitor}, results in {folder}")
    summary = pipeline.run(
        args.domain, args.competitor, folder, args.seed, args.crawl_minutes,
        args.max_urls, priority, args.link_budget, use_llm=not args.no_llm,
    )
    for name, value in summary.items():
        print(f"{name}: {value}")
    return 0
