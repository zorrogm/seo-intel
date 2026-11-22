import hashlib

import pytest

from fake_site import FakeSite
from seo_intel import config, pipeline
from seo_intel.plan import finalise, rationale_problem


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
        "action_plan.json", "action_plan.md", "cannibalization.json", "crawl_summary.json",
        "gaps.json", "internal_links.json", "near_duplicates.json",
    }


def test_second_run_is_byte_identical(sites, tmp_path):
    run(sites, tmp_path)
    first = digests(tmp_path)
    run(sites, tmp_path)
    assert digests(tmp_path) == first


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
    assert rationale_problem("Overlap is 82 percent [c1].", act) == "states a number or URL in prose"


def test_bad_rationale_is_regenerated():
    plan = finalise([action("a1", 1)], [{"id": "a1", "rationale": "Overlap is 82% [c1]"}], FakeFacts())
    assert "Evidence: [c1]" in plan["actions"][0]["rationale"]
    assert plan["rejections"][0]["result"] == "rationale regenerated"
