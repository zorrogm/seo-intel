import hashlib
import json
import sqlite3

import pytest

from fake_site import FakeSite
from seo_intel import config, pipeline
from tricky_site import TrickySite


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """One crawl of the tricky site, shared by tests."""
    folder = tmp_path_factory.mktemp("run")
    tricky, plain = TrickySite(), FakeSite()

    def run(hours=config.REVALIDATE_AFTER_HOURS):
        return pipeline.run(tricky.base, plain.base, folder, crawl_minutes=1.0, max_urls=5000,
                            gap_seconds=0.001, use_llm=False, revalidate_after_hours=hours)

    first = run()
    yield {"site": tricky, "folder": folder, "run": run, "first": first}
    tricky.close()
    plain.close()


def output(world, name):
    path = world["folder"] / config.OUTPUT_FOLDER / name
    return json.loads(path.read_text(encoding="utf-8"))


def digests(world):
    out = world["folder"] / config.OUTPUT_FOLDER
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())}


def test_traps_are_stopped_and_reported(world):
    site = world["site"]
    assert len(site.hit_paths("/shop")) <= config.MAX_QUERY_VARIANTS_PER_PATH + 1
    assert len(site.hit_paths("/loop/")) <= config.MAX_SEGMENT_REPEATS
    assert len(site.hit_paths("/cal/")) <= config.CALENDAR_MAX_PER_SHAPE
    traps = output(world, "spider_traps.json")[site.base.split("//")[1]]
    kinds = {t["kind"] for t in traps["traps"]}
    assert kinds == {"calendar", "faceted", "growing_path", "session_id"}
    assert all(t["pattern"] and t["example"] for t in traps["traps"])


def test_session_and_tracking_parameters_are_removed(world):
    site = world["site"]
    assert site.hits["/login"] == 1
    assert not [p for p in site.hits if "sid=" in p or "utm_" in p or "jsessionid" in p]


def test_nofollow_is_respected(world):
    site = world["site"]
    assert "/hidden1" not in site.hits
    assert "/hidden2" not in site.hits


def test_meta_and_script_redirects_are_recorded(world):
    db = sqlite3.connect(str(world["folder"] / config.CRAWL_DB_NAME))
    base = world["site"].base
    kinds = dict(db.execute(
        "SELECT u.url, p.redirect_kind FROM pages p JOIN urls u ON u.id = p.url_id"
        " WHERE p.redirect_kind != '' AND u.url LIKE ?", (base + "%",)
    ))
    assert kinds == {base + "/meta": "meta", base + "/js": "js"}
    chains = output(world, "crawl_issues.json")["redirect_chains"]
    assert {c["urls"][0]: c["kinds"] for c in chains} == {base + "/meta": ["meta"], base + "/js": ["js"]}


def test_soft_404s_are_found_without_false_alarms(world):
    base = world["site"].base
    rows = [row for row in output(world, "soft_404s.json") if row["url"].startswith(base)]
    found = {row["url"]: row["reason"] for row in rows}
    assert found == {
        base + "/gone": "title or heading says not found",
        base + "/empty": "page has no text",
        base + "/gone2": "same content as a missing page",
    }


def test_canonical_and_header_problems(world):
    base = world["site"].base
    issues = output(world, "crawl_issues.json")
    problems = {p["url"]: p["problem"] for p in issues["canonical_problems"]}
    assert problems == {
        base + "/canon-a": "canonical chain",
        base + "/canon-d": "canonical points to a 404",
    }
    assert issues["noindex_by_header"] == [base + "/xrobots"]


def test_first_run_reports_no_changes(world):
    assert world["first"]["crawl_mode"] == "crawl"
    assert output(world, "change_report.json") == {"crawl_number": 1, "sites": {}}


def test_rerun_same_day_is_identical(world):
    before = digests(world)
    hits = sum(world["site"].hits.values())
    assert world["run"]()["crawl_mode"] == "reuse"
    assert digests(world) == before
    assert sum(world["site"].hits.values()) == hits


def test_next_day_rerun_reports_changes(world):
    site = world["site"]
    site.changed = True
    hits = sum(site.hits.values())
    assert world["run"](hours=0)["crawl_mode"] == "revalidate"
    report = output(world, "change_report.json")
    changes = report["sites"][site.base.split("//")[1]]
    assert report["crawl_number"] == 2
    assert changes["new"] == [{"url": site.base + "/new-page"}]
    assert changes["removed"] == [{"url": site.base + "/b"}]
    assert changes["newly_redirected"] == [{"url": site.base + "/c", "redirects_to": site.base + "/a"}]
    assert changes["title_changed"] == [
        {"url": site.base + "/a", "old": "Sharpening guide", "new": "Sharpening guide updated"}
    ]
    # Unchanged pages answered 304, no body sent
    assert site.not_modified > 50
    assert sum(site.hits.values()) - hits < 2 * hits
