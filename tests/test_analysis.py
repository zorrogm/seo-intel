from seo_intel import analysis
from seo_intel.corpus import Page


def make(site, path, title, words):
    text = " ".join(words)
    return Page(url=f"http://{site}{path}", site=site, status=200, lang="en", title=title,
                h1=title, tokens=list(words), sentences=[text.capitalize() + "."])


def test_new_links_only_come_from_our_own_site():
    topic = ["rose", "pruning", "guide", "spring", "garden", "cut", "stem", "bud"] * 6
    other = ["engine", "oil", "filter", "change", "garage", "car", "litre", "bolt"] * 6
    ours = [make("ours.test", "/", "Home", other)]
    ours += [make("ours.test", f"/deep/{i}", "Rose pruning guide", topic + [f"x{i}"]) for i in range(4)]
    ours += [make("ours.test", f"/misc/{i}", f"Engine notes {i}", other + [f"y{i}"]) for i in range(12)]
    theirs = [make("theirs.test", f"/r/{i}", "Rose pruning guide", topic + [f"z{i}"]) for i in range(8)]
    ours.sort(key=lambda p: p.url)
    theirs.sort(key=lambda p: p.url)
    result = analysis.analyse_pages(ours, theirs, "ours.test", "theirs.test",
                                    "http://ours.test/", 0, None, 10)
    assert result.priority
    for link in result.new_links:
        assert result.pages[link["source"]].site == "ours.test"
        assert result.pages[link["target"]].site == "ours.test"


def test_versions_and_dates_are_a_series_not_competitors():
    from seo_intel.topics import healthy_reason

    def page(path, title):
        return Page(url="http://s.test" + path, site="s.test", status=200, title=title)

    final, candidate = page("/release/python-392/", "Python 3.9.2"), page("/release/python-392rc1/", "Python 3.9.2rc1")
    assert healthy_reason(final, candidate) == "numbered series"
    sep, octo = page("/press/pr20030923/", "Press Release 23-Sep-2003"), page("/press/pr20031003/", "Press Release 3-Oct-2003")
    assert healthy_reason(sep, octo) == "numbered series"
    # Same title, same text, different address: a real duplicate
    one, two = page("/release/python-335-rc1/", "Python 3.3.5rc1"), page("/release/python-335rc1/", "Python 3.3.5rc1")
    assert healthy_reason(one, two, overlap=0.9) == ""
    assert healthy_reason(page("/guides/roses/", "Pruning roses"), page("/blog/rose-care/", "Rose pruning tips")) == ""
