"""Page intent: rules first, LLM for ties."""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple
from urllib.parse import urlsplit

from seo_intel import config
from seo_intel.llm import Gemini, LLMError
from seo_intel.text import tokenize

_SYSTEM = (
    "Classify the search intent of web pages. For each numbered page reply "
    "with one word: informational, commercial, transactional or navigational. "
    "Call the classify tool once with one label per page, in order."
)
_TOOL = [{"functionDeclarations": [{
    "name": "classify",
    "description": "Give one intent label per page, in order.",
    "parameters": {"type": "OBJECT", "required": ["labels"], "properties": {
        "labels": {"type": "ARRAY", "items": {"type": "STRING", "enum": list(config.INTENTS)}}}},
}]}]


def score_intents(page, anchors: Sequence[str]) -> Dict[str, int]:
    strong = tokenize(page.title) + tokenize(page.h1) + tokenize(urlsplit(page.url).path)
    weak = [t for anchor in anchors for t in tokenize(anchor)]
    scores = {}
    for intent, words in config.INTENT_WORDS.items():
        scores[intent] = 2 * sum(t in words for t in strong) + sum(t in words for t in weak)
    # Several prices suggest a page that sells
    text = " ".join(page.sentences).lower()
    prices = sum(text.count(mark) for mark in config.INTENT_CURRENCY_MARKS)
    if prices >= config.INTENT_CURRENCY_MIN_HITS:
        scores["transactional"] += 2
    return scores


def rule_intent(page, anchors: Sequence[str]) -> Tuple[str, bool]:
    """Label, and whether the rules were unsure."""
    scores = score_intents(page, anchors)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], config.INTENTS.index(item[0])))
    best, best_score = ranked[0]
    runner_up = ranked[1][1]
    if best_score < config.INTENT_MIN_SCORE:
        # One weak hint is worth a second opinion
        return config.DEFAULT_INTENT, best_score > 0
    return best, best_score == runner_up


def _ask(llm: Gemini, batch: List) -> List[str]:
    lines = []
    for number, page in enumerate(batch, start=1):
        path = urlsplit(page.url).path[:80]
        lines.append(f"{number}. path: {path} | title: {page.title[:90]} | heading: {page.h1[:90]}")
    body = {
        "systemInstruction": {"parts": [{"text": _SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": "\n".join(lines)}]}],
        "tools": _TOOL,
        "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
    }
    reply = llm.generate(body)["candidates"][0]["content"]["parts"]
    labels = next(p["functionCall"]["args"]["labels"] for p in reply if "functionCall" in p)
    if len(labels) != len(batch) or any(label not in config.INTENTS for label in labels):
        raise LLMError("bad intent labels")
    return labels


def refine_with_llm(pages: List, intents: List[str], unsure: List[int], llm: Gemini) -> int:
    """Let the LLM settle unsure pages, within 2%."""
    limit = min(config.INTENT_LLM_MAX_PAGES, int(config.MAX_LLM_PAGE_SHARE * len(pages)))
    chosen = sorted(unsure, key=lambda i: pages[i].url)[:limit]
    settled = 0
    for start in range(0, len(chosen), config.INTENT_LLM_BATCH):
        batch = chosen[start : start + config.INTENT_LLM_BATCH]
        try:
            labels = _ask(llm, [pages[i] for i in batch])
        except (LLMError, KeyError, IndexError, TypeError, StopIteration) as exc:
            llm.last_error = f"intent: {type(exc).__name__}: {exc}"
            break
        for index, label in zip(batch, labels):
            intents[index] = label
        settled += len(batch)
    return settled
