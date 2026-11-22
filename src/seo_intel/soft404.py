"""Pages that say OK but are really missing."""
from __future__ import annotations

from seo_intel import config
from seo_intel.text import jaccard, set_overlap, shingles


def _says_missing(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in config.SOFT_404_PHRASES)


def soft_404_reason(page, probe) -> str:
    """Why a page is a soft 404, or empty."""
    if page.total_words <= config.SOFT_404_EMPTY_WORDS:
        return "page has no text"
    short = page.word_count <= config.SOFT_404_PHRASE_MAX_WORDS
    if short and (_says_missing(page.title) or _says_missing(page.h1)):
        return "title or heading says not found"
    # Compare with the site's own missing page
    if probe is None or probe.redirect_to or not probe.tokens:
        return ""
    ours, theirs = shingles(page.tokens), shingles(probe.tokens)
    if len(ours) and len(theirs):
        alike = jaccard(ours, theirs) >= config.SOFT_404_PROBE_OVERLAP
    else:
        alike = set_overlap(set(page.tokens), set(probe.tokens)) >= config.SOFT_404_PROBE_OVERLAP
    return "same content as a missing page" if alike else ""
