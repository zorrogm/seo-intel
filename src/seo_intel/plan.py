"""Turn findings into candidate actions with claims."""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List

from seo_intel import config
from seo_intel.analysis import Analysis
from seo_intel.facts import Facts

# Instructions only; facts live in the claims
ACTION_TEXT = {
    "fix_redirect_chain": "Point links and the first redirect straight at the final page.",
    "fix_canonical": "Point the canonical tag at the live, indexable version of the page.",
    "canonicalize": "Keep one page and point the canonical tag of the other at it.",
    "merge_301": "Merge the weaker page into the stronger one and add a permanent redirect.",
    "retarget_intent": "Rewrite one page for a different intent so the two stop competing.",
    "add_internal_link": "Add a link to this page from the quoted sentence, using words already there.",
    "create_page": "Create a page on this topic.",
    "do_nothing": "Leave these pages as they are.",
}
# Each reason is a sentence code can check
REASONS = {
    "near_copy": "Their text is almost the same {refs}.",
    "same_topic": "They cover the same topic {refs}.",
    "same_intent": "They answer the same search intent {refs}.",
    "links_split": "Internal links are split between them {refs}.",
    "few_links": "The page gets few internal links {refs}.",
    "sentence_ready": "A sentence that suits the link already exists {refs}.",
    "not_linked": "The source page does not link to it yet {refs}.",
    "several_hops": "The redirect passes through more than one hop {refs}.",
    "canonical_off_target": "The canonical tag points away from a clean page {refs}.",
    "competitor_deep": "The competitor has many pages on the topic {refs}.",
    "we_are_thin": "This site has little on the topic {refs}.",
}
_REF = re.compile(r"\[(c\d+)\]")
_ACTION_ID = re.compile(r"\ba\d+\b")
_BANNED = re.compile(r"\d|https?:|www\.", re.I)


def claim_text(claim: Dict, limit: int = 160) -> str:
    """One claim as a readable line."""
    value = claim["value"][:limit] if isinstance(claim["value"], str) else claim["value"]
    if "topic_id" in claim:
        return f"{claim['metric']} on topic {claim['topic_id']} for {claim['site']} = {value}"
    if "metric" in claim:
        return f"{claim['metric']} of {claim['url_a']} and {claim['url_b']} = {value}"
    return f"{claim['field']} of {claim['url']} = {value}"


def supported_reasons(action: Dict) -> Dict[str, List[str]]:
    """Reasons the action's claims prove, with their claims."""
    claims = action["claims"]

    def ids(test) -> List[str]:
        return [c["id"] for c in claims if test(c)]

    pair = lambda name: (lambda c: "url_a" in c and c["metric"] == name)
    field = lambda name: (lambda c: c.get("field") == name)
    found: Dict[str, List[str]] = {}
    kind = action["type"]
    if kind in ("canonicalize", "merge_301", "retarget_intent"):
        overlap = [c for c in claims if pair("content_overlap")(c)]
        if overlap and overlap[0]["value"] >= config.NEAR_DUPLICATE_OVERLAP:
            found["near_copy"] = [overlap[0]["id"]]
        similar = [c for c in claims if pair("topic_similarity")(c)]
        if similar and similar[0]["value"] >= config.CANNIBAL_MIN_SIMILARITY:
            found["same_topic"] = [similar[0]["id"]]
        intents = [c for c in claims if field("intent")(c)]
        if len(intents) >= 2 and len({c["value"] for c in intents}) == 1:
            found["same_intent"] = [c["id"] for c in intents]
        links = [c for c in claims if field("inlinks")(c)]
        if len(links) >= 2 and all(c["value"] >= 1 for c in links):
            found["links_split"] = [c["id"] for c in links]
    elif kind == "add_internal_link":
        few = ids(lambda c: field("inlinks")(c) and c["value"] <= config.FEW_INLINKS)
        if few:
            found["few_links"] = few
        if ids(field("sentence")):
            found["sentence_ready"] = ids(field("sentence"))
        missing = ids(lambda c: pair("links_to")(c) and c["value"] is False)
        if missing:
            found["not_linked"] = missing
    elif kind == "fix_redirect_chain":
        if len(ids(field("redirect_to"))) >= 2:
            found["several_hops"] = ids(field("redirect_to"))
    elif kind == "fix_canonical":
        found["canonical_off_target"] = [c["id"] for c in claims]
    elif kind == "create_page":
        theirs = ids(lambda c: "topic_id" in c and c["site"] != action.get("target_site")
                     and c["metric"] == "pages" and c["value"] >= config.GAP_MIN_PAGES)
        if theirs:
            found["competitor_deep"] = theirs
        ours = ids(lambda c: "topic_id" in c and c["site"] == action.get("target_site"))
        if ours:
            found["we_are_thin"] = ours
    return found


def write_rationale(action: Dict, wanted: List[str]) -> str:
    """Instruction plus checked reasons, nothing else."""
    supported = supported_reasons(action)
    codes = [code for code in wanted if code in supported] or list(supported)
    codes = list(dict.fromkeys(codes))[: config.MAX_REASONS_PER_ACTION]
    parts = [ACTION_TEXT[action["type"]]]
    used = set()
    for code in codes:
        refs = supported[code]
        used.update(refs)
        parts.append(REASONS[code].format(refs=" ".join(f"[{ref}]" for ref in refs)))
    rest = [c["id"] for c in action["claims"] if c["id"] not in used]
    if rest:
        parts.append("Pages and other evidence: " + " ".join(f"[{ref}]" for ref in rest) + ".")
    return " ".join(parts)


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
        score = group["severity"]
        if overlap >= config.NEAR_DUPLICATE_OVERLAP:
            kind = "canonicalize"
        elif overlap >= config.MERGE_MIN_OVERLAP and score >= config.MERGE_MIN_SEVERITY:
            kind = "merge_301"
        else:
            # Little shared text: tell them apart, do not merge
            kind = "retarget_intent"
            score *= config.RETARGET_SCORE_FACTOR
        claims = [
            _field(facts, url_a, "title"), _field(facts, url_b, "title"),
            _field(facts, url_a, "intent"), _field(facts, url_b, "intent"),
            _metric(facts, url_a, url_b, "content_overlap"),
            _metric(facts, url_a, url_b, "topic_similarity"),
            _field(facts, url_a, "inlinks"), _field(facts, url_b, "inlinks"),
        ]
        actions.append({
            "type": kind, "score": score, "urls": group["urls"],
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
        topic = gap["topic_id"]
        claims = [
            {"topic_id": topic, "site": a.competitor_site, "metric": "pages",
             "value": gap["competitor_pages"]},
            {"topic_id": topic, "site": a.competitor_site, "metric": "words",
             "value": gap["competitor_words"]},
            {"topic_id": topic, "site": a.target_site, "metric": "pages",
             "value": gap["target_pages"]},
            {"topic_id": topic, "site": a.target_site, "metric": "words",
             "value": gap["target_words"]},
        ]
        claims += [_field(facts, url, "title") for url in gap["examples"]]
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
        action["target_site"] = a.target_site
        for claim in action["claims"]:
            claim_number += 1
            claim["id"] = f"c{claim_number}"
    return actions


def rationale_problem(text: str, action: Dict) -> str:
    """Why a rationale breaks the prose rules."""
    allowed = {c["id"] for c in action["claims"]}
    refs = set(_REF.findall(text))
    if not refs:
        return "no claim reference"
    if not refs <= allowed:
        return "references a claim it does not own"
    # Action names like a12 are not facts
    if _BANNED.search(_ACTION_ID.sub("", _REF.sub("", text))):
        return "states a number or URL in prose"
    return ""


def finalise(candidates: List[Dict], chosen: List[Dict], facts: Facts, live=None) -> Dict:
    """Verify every claim and build the final plan."""
    by_id = {c["id"]: c for c in candidates}
    order, reasons_of = [], {}
    for pick in chosen:
        if isinstance(pick, dict) and pick.get("id") in by_id and pick["id"] not in reasons_of:
            order.append(pick["id"])
            wanted = pick.get("reasons")
            reasons_of[pick["id"]] = [str(r) for r in wanted] if isinstance(wanted, list) else []
    # The agent's picks first, then the best of the rest
    order += [c["id"] for c in candidates if c["id"] not in reasons_of]
    # No action type may crowd out the others
    per_type = Counter()
    first, later = [], []
    for action_id in order:
        kind = by_id[action_id]["type"]
        if per_type[kind] < config.PLAN_MAX_PER_TYPE:
            per_type[kind] += 1
            first.append(action_id)
        else:
            later.append(action_id)
    order = first + later

    actions, rejections = [], []
    for action_id in order:
        if len(actions) >= config.PLAN_ACTIONS:
            break
        action = dict(by_id[action_id])
        verified = []
        for claim in action["claims"]:
            passed, actual = facts.check(claim)
            # The live site gets the last word
            if passed and live is not None and live(claim) is False:
                passed, actual = False, "changed on the live site"
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
        wanted = reasons_of.get(action_id, [])
        unsupported = [code for code in wanted if code not in supported_reasons(action)]
        if unsupported:
            rejections.append({"action": action_id, "reasons": unsupported,
                               "result": "unsupported reasons removed"})
        action["rationale"] = write_rationale(action, wanted)
        action["rank"] = len(actions) + 1
        action.pop("target_site", None)
        actions.append(action)
    return {"actions": actions, "rejections": rejections}
