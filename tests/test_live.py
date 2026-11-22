from seo_intel.live import LiveCheck
from seo_intel.store import Store
from tricky_site import TrickySite


def test_live_check_sees_a_changed_title(tmp_path):
    site = TrickySite()
    try:
        store = Store(tmp_path / "crawl.sqlite", 100)
        live = LiveCheck(store, 0.001)
        url = site.base + "/a"
        title = {"id": "c1", "url": url, "field": "title", "value": "Sharpening guide"}
        actions = [{"claims": [title, {"id": "c2", "url": url, "field": "inlinks", "value": 3}]}]
        assert live.pending(actions) == [url]
        live.fetch([url])
        assert live.pending(actions) == []
        assert live.verdict(title) is True
        # Computed numbers are not live facts
        assert live.verdict(actions[0]["claims"][1]) is None
        sentence = {"id": "c3", "url": url, "field": "sentence",
                    "value": "This paragraph talks about gardening tools and how to keep them sharp all year."}
        assert live.verdict(sentence) is True

        site.changed = True
        assert LiveCheck(store, 0.001).verdict(title) is True
        fresh = LiveCheck(store, 0.001, max_age_hours=0)
        fresh.fetch([url])
        assert fresh.verdict(title) is False
        gone = {"id": "c4", "url": site.base + "/b", "field": "status", "value": 200}
        fresh.fetch([gone["url"]])
        assert fresh.verdict(gone) is False
        store.close()
    finally:
        site.close()
