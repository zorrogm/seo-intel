"""Quick scan of a page during the crawl."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from selectolax.lexbor import LexborHTMLParser

from seo_intel import config
from seo_intel.text import tokenize
from seo_intel.urls import normalize, session_param

_REFRESH = re.compile(r"^\s*(\d+)\s*[;,]\s*(?:url\s*=\s*)?[\"']?\s*([^\"'\s][^\"']*)", re.I)
_JS_REDIRECT = re.compile(
    r"(?:window\.|document\.|top\.|self\.)?location(?:\.href)?\s*=\s*[\"']([^\"']+)[\"']"
    r"|location\.(?:replace|assign)\(\s*[\"']([^\"']+)[\"']"
)


@dataclass
class PageScan:
    links: List[str] = field(default_factory=list)
    redirect_to: str = ""
    redirect_kind: str = ""
    nofollow: bool = False
    session_params: List[str] = field(default_factory=list)


def _meta_refresh(tree, base: str, page_url: str) -> str:
    for tag in tree.css("meta"):
        if (tag.attributes.get("http-equiv") or "").lower() != "refresh":
            continue
        match = _REFRESH.match(tag.attributes.get("content") or "")
        if match and int(match.group(1)) <= config.META_REFRESH_MAX_SECONDS:
            target = normalize(match.group(2), base)
            if target and target != page_url:
                return target
    return ""


def _js_redirect(tree, base: str, page_url: str) -> str:
    """A script redirect on a nearly empty page."""
    target = ""
    for tag in tree.css("script"):
        if tag.attributes.get("src"):
            continue
        match = _JS_REDIRECT.search(tag.text(deep=True) or "")
        if match:
            target = normalize(match.group(1) or match.group(2), base) or ""
            break
    if not target or target == page_url or tree.body is None:
        return ""
    tree.strip_tags(list(config.STRIP_TAGS))
    words = len(tokenize(tree.body.text(deep=True, separator=" ")))
    return target if words <= config.JS_REDIRECT_MAX_WORDS else ""


def scan_page(body: bytes, page_url: str) -> PageScan:
    tree = LexborHTMLParser(body)
    scan = PageScan()
    base = page_url
    base_tag = tree.css_first("base[href]")
    if base_tag is not None:
        base = normalize(base_tag.attributes.get("href") or "", page_url) or page_url
    robots_tag = tree.css_first('meta[name="robots"]')
    if robots_tag is not None:
        content = (robots_tag.attributes.get("content") or "").lower()
        scan.nofollow = "nofollow" in content or "none" in content

    seen = set()
    for tag in tree.css("a[href]"):
        href = tag.attributes.get("href") or ""
        url = normalize(href, base)
        if not url or url in seen:
            continue
        seen.add(url)
        name = session_param(href)
        if name:
            scan.session_params.append(name)
        # Links marked nofollow are not crawled
        if "nofollow" not in (tag.attributes.get("rel") or "").lower():
            scan.links.append(url)

    scan.redirect_to = _meta_refresh(tree, base, page_url)
    scan.redirect_kind = "meta" if scan.redirect_to else ""
    if not scan.redirect_to:
        scan.redirect_to = _js_redirect(tree, base, page_url)
        scan.redirect_kind = "js" if scan.redirect_to else ""
    return scan
