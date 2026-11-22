"""Page fields and main content, learned per site."""
from __future__ import annotations

import zlib
from collections import Counter
from typing import Dict, List, Set

from selectolax.lexbor import LexborHTMLParser

from seo_intel import config
from seo_intel.text import clean
from seo_intel.urls import normalize

_BLOCK = frozenset(config.BLOCK_TAGS)
_CHROME = frozenset(config.CHROME_TAGS)
_CONTENT_ROOTS = frozenset(("article", "main"))


def _attr(tree, selector: str, name: str) -> str:
    node = tree.css_first(selector)
    return (node.attributes.get(name) or "").strip() if node is not None else ""


def _text(node) -> str:
    return clean(node.text(deep=True, separator=" ")) if node is not None else ""


def _ancestry(node):
    """Tag path, chrome flag and wrapping link."""
    tags, wrap_href = [], ""
    current = node
    while current is not None and current.tag not in ("html", "-undef"):
        tags.append(current.tag)
        if current.tag == "a" and not wrap_href:
            wrap_href = current.attributes.get("href") or ""
        current = current.parent
    tags.reverse()
    chrome = any(t in _CHROME for t in tags)
    # A header inside an article is content
    if "header" in tags and not any(t in _CONTENT_ROOTS for t in tags):
        chrome = True
    return "/".join(tags), chrome, wrap_href


def parse_page(body: bytes, url: str) -> Dict:
    """Fields, text blocks and links of one page."""
    tree = LexborHTMLParser(body)
    base = normalize(_attr(tree, "base[href]", "href"), url) or url
    canonical = _attr(tree, 'link[rel="canonical"]', "href")
    alternates = []
    for tag in tree.css('link[rel="alternate"][hreflang]'):
        alt = normalize(tag.attributes.get("href") or "", base)
        if alt:
            alternates.append(alt)
    page = {
        "title": _text(tree.css_first("title")),
        "h1": _text(tree.css_first("h1")),
        "canonical": normalize(canonical, base) or "" if canonical else "",
        "meta_robots": _attr(tree, 'meta[name="robots"]', "content").lower(),
        "hreflang": sorted(set(alternates)),
        "blocks": [],
    }
    root = tree.body
    if root is None:
        return page
    tree.strip_tags(list(config.STRIP_TAGS))

    block_nodes = [n for n in root.traverse() if n.tag in _BLOCK]
    parents: Set[int] = set()
    for node in block_nodes:
        current = node.parent
        while current is not None and current.mem_id not in parents:
            parents.add(current.mem_id)
            current = current.parent

    # Group links under their nearest block
    links_by_block: Dict[int, List] = {}
    for tag in root.css("a[href]"):
        current = tag.parent
        while current is not None and current.tag not in _BLOCK:
            current = current.parent
        if current is None:
            continue
        target = normalize(tag.attributes.get("href") or "", base)
        if target:
            links_by_block.setdefault(current.mem_id, []).append([target, _text(tag)])

    for node in block_nodes:
        links = links_by_block.get(node.mem_id, [])
        path, chrome, wrap_href = _ancestry(node)
        if node.mem_id in parents:
            # Loose links beside other blocks
            for link in links:
                page["blocks"].append([path + "/a", int(chrome), link[1], [link]])
            continue
        text = _text(node)
        wrapped = normalize(wrap_href, base) if wrap_href else None
        if wrapped:
            links = links + [[wrapped, text]]
        if text or links:
            page["blocks"].append([path, int(chrome), text, links])
    return page


def block_key(block: List) -> int:
    return zlib.crc32(block[2].lower().encode("utf-8"))


def learn_template(sample: List[Dict]) -> Set[int]:
    """Blocks repeated across many pages are template."""
    seen = Counter()
    for page in sample:
        seen.update({block_key(b) for b in page["blocks"]})
    needed = max(config.TEMPLATE_MIN_PAGES, config.TEMPLATE_MIN_SHARE * len(sample))
    return {key for key, count in seen.items() if count >= needed}


def is_template(block: List, template: Set[int]) -> bool:
    return bool(block[1]) or block_key(block) in template
