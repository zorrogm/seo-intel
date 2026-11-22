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
