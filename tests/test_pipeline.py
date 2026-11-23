import hashlib

import pytest

from fake_site import FakeSite
from seo_intel import config, pipeline
from seo_intel.plan import finalise, rationale_problem, supported_reasons


@pytest.fixture
def sites():
    pair = FakeSite(), FakeSite()
    yield pair
    for site in pair:
        site.close()


def run(sites, folder):
    return pipeline.run(sites[0].base, sites[1].base, folder, crawl_minutes=1.0,
                        max_urls=1000, gap_seconds=0.001, use_llm=False)


def digests(folder):
    out = folder / config.OUTPUT_FOLDER
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())}


def test_full_run_writes_every_output(sites, tmp_path):
    summary = run(sites, tmp_path)
    assert summary["pages"] > 0
    names = set(digests(tmp_path))
    assert names == {
        "action_plan.json", "action_plan.md", "cannibalization.json", "change_report.json",
        "crawl_issues.json", "crawl_summary.json", "gaps.json", "internal_links.json",
        "near_duplicates.json", "render_report.json", "soft_404s.json", "spider_traps.json",
    }


def test_second_run_is_byte_identical(sites, tmp_path):
    run(sites, tmp_path)
    first = digests(tmp_path)
    run(sites, tmp_path)
    assert digests(tmp_path) == first


class Truthful:
    def check(self, claim):
        return True, claim["value"]


class FakeFacts:
    """Says a claim is true when value is 1."""

    def check(self, claim):
        return claim["value"] == 1, claim["value"]


def action(action_id, value):
    return {"id": action_id, "type": "merge_301", "score": 0.5, "urls": ["u"],
            "claims": [{"id": "c" + action_id[1:], "url": "u", "field": "status", "value": value}]}


def test_false_claim_drops_the_action():
    plan = finalise([action("a1", 1), action("a2", 0)], [], FakeFacts())
    assert [a["id"] for a in plan["actions"]] == ["a1"]
    results = [r["result"] for r in plan["rejections"]]
    assert results == ["claim removed", "action dropped"]


def test_rationale_rules():
    act = action("a1", 1)
    assert rationale_problem("Merge them, see [c1].", act) == ""
    assert rationale_problem("Merge them.", act) == "no claim reference"
    assert rationale_problem("See [c9].", act) == "references a claim it does not own"
    assert rationale_problem("Action a1 is backed by [c1].", act) == ""
    assert rationale_problem("Overlap is 82 percent [c1].", act) == "states a number or URL in prose"


def cannibal_action(overlap):
    claims = [
        {"id": "c1", "url": "u1", "field": "intent", "value": "informational"},
        {"id": "c2", "url": "u2", "field": "intent", "value": "informational"},
        {"id": "c3", "url_a": "u1", "url_b": "u2", "metric": "content_overlap", "value": overlap},
        {"id": "c4", "url_a": "u1", "url_b": "u2", "metric": "topic_similarity", "value": 0.9},
    ]
    return {"id": "a1", "type": "merge_301", "score": 0.7, "urls": ["u1", "u2"], "claims": claims}


def test_reasons_come_only_from_what_claims_prove():
    assert list(supported_reasons(cannibal_action(0.95))) == ["near_copy", "same_topic", "same_intent"]
    assert "near_copy" not in supported_reasons(cannibal_action(0.3))


def test_unsupported_reason_is_removed_and_logged():
    picks = [{"id": "a1", "reasons": ["near_copy", "same_topic"]}]
    plan = finalise([cannibal_action(0.3)], picks, Truthful())
    text = plan["actions"][0]["rationale"]
    assert "almost the same" not in text
    assert "They cover the same topic [c4]." in text
    assert plan["rejections"] == [
        {"action": "a1", "reasons": ["near_copy"], "result": "unsupported reasons removed"}
    ]
    assert rationale_problem(text, plan["actions"][0]) == ""


def test_rationale_without_picks_uses_every_proven_reason():
    plan = finalise([cannibal_action(0.95)], [], Truthful())
    text = plan["actions"][0]["rationale"]
    assert text.startswith("Merge the weaker page into the stronger one")
    assert "[c3]" in text and "[c4]" in text and "[c1] [c2]" in text


def test_live_change_drops_the_action():
    changed = lambda claim: False if claim["id"] == "c2" else None
    plan = finalise([action("a1", 1), action("a2", 1)], [], FakeFacts(), changed)
    assert [a["id"] for a in plan["actions"]] == ["a1"]
    assert "changed on the live site" in plan["rejections"][0]["found"]
