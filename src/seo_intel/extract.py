"""Page fields and main content, learned per site."""
from __future__ import annotations

import re
import zlib
from collections import Counter
from typing import Dict, List, Set

from selectolax.lexbor import LexborHTMLParser

from seo_intel import config
from seo_intel.text import clean, tokenize
from seo_intel.urls import normalize

_BLOCK = frozenset(config.BLOCK_TAGS)
_CHROME = frozenset(config.CHROME_TAGS)
_CONTENT_ROOTS = frozenset(("article", "main"))
_DIGITS = re.compile(r"\d+")


def _attr(tree, selector: str, name: str) -> str:
    node = tree.css_first(selector)
    return (node.attributes.get(name) or "").strip() if node is not None else ""


def _text(node) -> str:
    return clean(node.text(deep=True, separator=" ")) if node is not None else ""


def _label(node) -> str:
    """Tag plus its first class, numbers masked."""
    name = (node.attributes.get("class") or "").split()
    if name:
        return node.tag + "." + _DIGITS.sub("0", name[0])
    return node.tag


def _ancestry(node):
    """Tag path, chrome flag and wrapping link."""
    tags, labels, wrap_href = [], [], ""
    current = node
    while current is not None and current.tag not in ("html", "-undef"):
        tags.append(current.tag)
        # Class names only near the block itself
        labels.append(_label(current) if len(tags) <= config.PATH_LABEL_LEVELS else current.tag)
        if current.tag == "a" and not wrap_href:
            wrap_href = current.attributes.get("href") or ""
        current = current.parent
    labels.reverse()
    chrome = any(t in _CHROME for t in tags)
    # A header inside an article is content
    if "header" in tags and not any(t in _CONTENT_ROOTS for t in tags):
        chrome = True
    return "/".join(labels), chrome, wrap_href


def _loose_text(node, parents: Set[int]) -> str:
    """Direct text of a block that has child blocks."""
    pieces = []
    for child in node.iter(include_text=True):
        if child.tag in _BLOCK or child.mem_id in parents:
            continue
        pieces.append(child.text(deep=True, separator=" "))
    return clean(" ".join(pieces))


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
            # Text sitting beside child blocks
            text = _loose_text(node, parents)
            if text or links:
                page["blocks"].append([path + "/text", int(chrome), text, links])
            continue
        text = _text(node)
        wrapped = normalize(wrap_href, base) if wrap_href else None
        if wrapped:
            links = links + [[wrapped, text]]
        if text or links:
            page["blocks"].append([path, int(chrome), text, links])
    return page


def block_key(block: List) -> int:
    """Same key when only numbers differ."""
    return zlib.crc32(_DIGITS.sub("0", block[2].lower()).encode("utf-8"))


def _link_density(block: List) -> float:
    words = len(tokenize(block[2]))
    linked = sum(len(tokenize(anchor)) for _url, anchor in block[3])
    return min(1.0, linked / words) if words else (1.0 if block[3] else 0.0)


class Template:
    """What one site repeats around its content."""

    def __init__(self, repeated: Set[int], chrome_paths: Set[str]):
        self.repeated = repeated
        self.chrome_paths = chrome_paths


def learn_template(sample: List[Dict]) -> Template:
    """Find repeated blocks and link heavy positions."""
    seen = Counter()
    path_pages = Counter()
    path_density: Dict[str, List[float]] = {}
    for page in sample:
        seen.update({block_key(b) for b in page["blocks"]})
        path_pages.update({b[0] for b in page["blocks"]})
        for block in page["blocks"]:
            path_density.setdefault(block[0], []).append(_link_density(block))
    needed = max(config.TEMPLATE_MIN_PAGES, config.TEMPLATE_MIN_SHARE * len(sample))
    repeated = {key for key, count in seen.items() if count >= needed}
    path_needed = max(config.TEMPLATE_MIN_PAGES, config.CHROME_PATH_MIN_SHARE * len(sample))
    chrome_paths = set()
    for path, pages in path_pages.items():
        density = sum(path_density[path]) / len(path_density[path])
        if pages >= path_needed and density >= config.CHROME_PATH_LINK_DENSITY:
            chrome_paths.add(path)
    return Template(repeated, chrome_paths)


def is_template(block: List, template: Template) -> bool:
    if block[1] or block_key(block) in template.repeated:
        return True
    return block[0] in template.chrome_paths


def main_blocks(page: Dict, template: Template) -> List[str]:
    """Text blocks that are real content."""
    return [b[2] for b in page["blocks"] if b[2] and not is_template(b, template)]
