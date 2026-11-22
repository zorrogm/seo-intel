"""Turn findings into candidate actions with claims."""
from __future__ import annotations

import re
from typing import Dict, List

from seo_intel import config
from seo_intel.analysis import Analysis
from seo_intel.facts import Facts

ACTION_TEXT = {
    "fix_redirect_chain": "This URL redirects through more than one hop. Point links and the first redirect straight at the final page.",
    "fix_canonical": "The canonical tag points at a page that is not a clean final page. Point it at the live, indexable version.",
    "canonicalize": "These pages are near copies of each other. Keep one and set the canonical tag of the other to it.",
    "merge_301": "These pages compete for the same intent. Merge the weaker page into the stronger one and add a permanent redirect.",
    "retarget_intent": "These pages overlap in topic and intent. Rewrite one to serve a different intent so they stop competing.",
    "add_internal_link": "This priority page deserves more internal links. Add a link from the quoted sentence using words already there.",
    "create_page": "The competitor covers this topic in depth and this site barely does. Create a page for it.",
    "do_nothing": "These similar pages are a healthy pair. Leave them as they are.",
}
_REF = re.compile(r"\[(c\d+)\]")
_LOOSE_REF = re.compile(r"\[?\b(c\d+)\b\]?")
_BANNED = re.compile(r"\d|https?:|www\.", re.I)


def _field(facts: Facts, url: str, name: str) -> Dict:
    return {"url": url, "field": name, "value": facts.field(url, name)}


def _metric(facts: Facts, a: str, b: str, name: str) -> Dict:
    return {"url_a": a, "url_b": b, "metric": name, "value": facts.metric(a, b, name)}


def _redirect_actions(a: Analysis, facts: Facts) -> List[Dict]:
    hops = {p.url: p.redirect_to for p in a.pages[: a.target_count] if p.redirect_to}
    targets = set(hops.values())
    actions = []
    for start in sorted(hops):
        # Only report a chain from its first URL
        if start in targets:
            continue
        chain, url = [start], hops[start]
        while url in hops and url not in chain and len(chain) < config.START_MAX_REDIRECTS:
            chain.append(url)
            url = hops[url]
        if len(chain) < 2:
            continue
        claims = [_field(facts, u, "redirect_to") for u in chain]
        actions.append({
            "type": "fix_redirect_chain", "score": min(0.9, 0.4 + 0.1 * len(chain)),
            "urls": chain, "claims": claims,
        })
    return actions


def _canonical_actions(a: Analysis, facts: Facts) -> List[Dict]:
    actions = []
    for page in a.pages[: a.target_count]:
        if page.status != 200 or page.canonical in ("", page.url) or not facts.knows(page.canonical):
            continue
        other = a.pages[a.index[page.canonical]]
        claims = [_field(facts, page.url, "canonical")]
        if other.status != 200:
            claims.append(_field(facts, other.url, "status"))
        elif other.canonical not in ("", other.url):
            claims.append(_field(facts, other.url, "canonical"))
        else:
            continue
        actions.append({
            "type": "fix_canonical", "score": 0.55,
            "urls": [page.url, other.url], "claims": claims,
        })
    return actions


def _group_actions(a: Analysis, facts: Facts) -> List[Dict]:
    actions = []
    for group in a.groups:
        pair = group["worst_pair"]
        url_a, url_b = pair["url_a"], pair["url_b"]
        overlap = pair["signals"]["content_overlap"]
        if overlap >= config.NEAR_DUPLICATE_OVERLAP:
            kind = "canonicalize"
        elif group["severity"] >= 0.6:
            kind = "merge_301"
        else:
            kind = "retarget_intent"
        claims = [
            _field(facts, url_a, "title"), _field(facts, url_b, "title"),
            _field(facts, url_a, "intent"), _field(facts, url_b, "intent"),
            _metric(facts, url_a, url_b, "content_overlap"),
            _metric(facts, url_a, url_b, "topic_similarity"),
            _field(facts, url_a, "inlinks"), _field(facts, url_b, "inlinks"),
        ]
        actions.append({
            "type": kind, "score": group["severity"], "urls": group["urls"],
            "claims": claims, "keep": group["keep"],
        })
    return actions


def _link_actions(a: Analysis, facts: Facts) -> List[Dict]:
    by_target: Dict[int, List[Dict]] = {}
    for link in a.new_links:
        by_target.setdefault(link["target"], []).append(link)
    gains = {t: float(a.rank_after[t] - a.rank[t]) for t in by_target}
    top = max(gains.values(), default=0.0) or 1.0
    actions = []
    for target in sorted(by_target, key=lambda t: a.pages[t].url):
        target_url = a.pages[target].url
        claims = [_field(facts, target_url, "title"), _field(facts, target_url, "inlinks")]
        links = []
        for link in by_target[target]:
            source_url = a.pages[link["source"]].url
            claims.append({"url": source_url, "field": "sentence", "value": link["sentence"]})
            claims.append(_metric(facts, source_url, target_url, "links_to"))
            links.append({"source": source_url, "sentence": link["sentence"], "anchor": link["anchor"]})
        actions.append({
            "type": "add_internal_link", "score": 0.2 + 0.5 * max(0.0, gains[target]) / top,
            "urls": [target_url] + [l["source"] for l in links],
            "claims": claims, "links": links,
        })
    return actions


def _gap_actions(a: Analysis, facts: Facts) -> List[Dict]:
    actions = []
    for gap in a.gaps:
        claims = [_field(facts, url, "title") for url in gap["examples"]]
        depth = min(1.0, gap["competitor_words"] / 10000)
        actions.append({
            "type": "create_page", "score": 0.3 + 0.4 * depth,
            "urls": gap["examples"], "claims": claims, "topic": gap["topic"],
        })
    return actions


def _healthy_actions(a: Analysis, facts: Facts) -> List[Dict]:
    actions = []
    for pair in a.healthy[: config.PLAN_ACTIONS]:
        urls = [pair["url_a"], pair["url_b"]]
        claims = [_field(facts, u, "title") for u in urls]
        claims.append(_metric(facts, urls[0], urls[1], "topic_similarity"))
        actions.append({
            "type": "do_nothing", "score": 0.05, "urls": urls,
            "claims": claims, "reason": pair["reason"],
        })
    return actions


def build_candidates(a: Analysis, facts: Facts) -> List[Dict]:
    """Every possible action, best first, with IDs."""
    actions = (
        _redirect_actions(a, facts) + _canonical_actions(a, facts) + _group_actions(a, facts)
        + _link_actions(a, facts) + _gap_actions(a, facts) + _healthy_actions(a, facts)
    )
    actions.sort(key=lambda x: (-x["score"], x["type"], x["urls"]))
    claim_number = 0
    for number, action in enumerate(actions, start=1):
        action["id"] = f"a{number}"
        action["score"] = round(action["score"], config.FLOAT_DIGITS)
        for claim in action["claims"]:
            claim_number += 1
            claim["id"] = f"c{claim_number}"
    return actions


def template_rationale(action: Dict) -> str:
    refs = " ".join(f"[{c['id']}]" for c in action["claims"])
    return f"{ACTION_TEXT[action['type']]} Evidence: {refs}"


def rationale_problem(text: str, action: Dict) -> str:
    """Why a written rationale breaks the rules."""
    allowed = {c["id"] for c in action["claims"]}
    refs = set(_REF.findall(text))
    if not refs:
        return "no claim reference"
    if not refs <= allowed:
        return "references a claim it does not own"
    if _BANNED.search(_REF.sub("", text)):
        return "states a number or URL in prose"
    return ""


def finalise(candidates: List[Dict], chosen: List[Dict], facts: Facts) -> Dict:
    """Verify every claim and build the final plan."""
    by_id = {c["id"]: c for c in candidates}
    order, rationale_of = [], {}
    for pick in chosen:
        if pick.get("id") in by_id and pick["id"] not in rationale_of:
            order.append(pick["id"])
            rationale_of[pick["id"]] = str(pick.get("rationale", ""))
    # Fill up with the best remaining candidates
    order += [c["id"] for c in candidates if c["id"] not in rationale_of]

    actions, rejections = [], []
    for action_id in order:
        if len(actions) >= config.PLAN_ACTIONS:
            break
        action = dict(by_id[action_id])
        verified = []
        for claim in action["claims"]:
            passed, actual = facts.check(claim)
            if passed:
                verified.append(claim)
            else:
                rejections.append({"action": action_id, "claim": claim, "found": repr(actual),
                                   "result": "claim removed"})
        if len(verified) < len(action["claims"]) and action["type"] != "do_nothing":
            # A failed claim undermines the whole action
            rejections.append({"action": action_id, "result": "action dropped"})
            continue
        action["claims"] = verified
        # Accept c12 written without brackets
        text = _LOOSE_REF.sub(r"[\1]", rationale_of.get(action_id, ""))
        problem = rationale_problem(text, action) if text else "no rationale written"
        if problem:
            if text:
                rejections.append({"action": action_id, "rationale": text, "problem": problem,
                                   "result": "rationale regenerated"})
            text = template_rationale(action)
        action["rationale"] = text
        action["rank"] = len(actions) + 1
        actions.append(action)
    return {"actions": actions, "rejections": rejections}
