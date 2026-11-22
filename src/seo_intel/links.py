"""Find the links on a page."""
from __future__ import annotations

from typing import List

from selectolax.lexbor import LexborHTMLParser

from seo_intel.urls import normalize


def extract_links(body: bytes, page_url: str) -> List[str]:
    """Clean absolute links, in page order."""
    tree = LexborHTMLParser(body)
    base = page_url
    base_tag = tree.css_first("base[href]")
    if base_tag is not None:
        base = normalize(base_tag.attributes.get("href") or "", page_url) or page_url
    seen, links = set(), []
    for tag in tree.css("a[href]"):
        url = normalize(tag.attributes.get("href") or "", base)
        if url and url not in seen:
            seen.add(url)
            links.append(url)
    return links
