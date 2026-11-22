"""Command line entry point for seo-intel."""
from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path

from seo_intel import config
from seo_intel.crawl import crawl_sites


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seo-intel")
    parser.add_argument("domain", help="site to analyse")
    parser.add_argument("--competitor", required=True, help="site to compare against")
    parser.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    parser.add_argument("--out", default=config.OUTPUT_DIR_NAME)
    parser.add_argument("--crawl-minutes", type=float, default=config.CRAWL_MINUTES)
    parser.add_argument("--max-urls", type=int, default=config.MAX_URLS_PER_SITE)
    return parser


def run_dir(out: str, domain: str, competitor: str) -> Path:
    """One folder per site pair, reused on rerun."""
    slug = lambda text: re.sub(r"[^a-z0-9.-]+", "_", text.lower()).strip("_")
    return Path(out) / f"{slug(domain)}__{slug(competitor)}"


def main() -> int:
    args = build_parser().parse_args()
    folder = run_dir(args.out, args.domain, args.competitor)
    print(f"Crawling {args.domain} and {args.competitor} into {folder}")
    summary = asyncio.run(
        crawl_sites([args.domain, args.competitor], folder, args.crawl_minutes, args.max_urls)
    )
    for domain, counts in summary.items():
        print(f"{domain}: {counts}")
    return 0
