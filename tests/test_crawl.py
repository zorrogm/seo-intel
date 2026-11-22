import asyncio
import signal
import sqlite3
import subprocess
import sys
import time

import pytest

from fake_site import PAGES, FakeSite
from seo_intel import config
from seo_intel.crawl import crawl_sites, sitemap_locs
from seo_intel.fetch import HostLimiter

# Home, pages, sitemap page, old, two loop pages
EXPECTED_FETCHED = 1 + PAGES + 1 + 1 + 2


@pytest.fixture
def site():
    fake = FakeSite()
    yield fake
    fake.close()


def crawl(site, folder, minutes=1.0, gap=0.001):
    return asyncio.run(crawl_sites([site.base], folder, minutes, 1000, gap))[site.base]


def test_full_crawl(site, tmp_path):
    counts = crawl(site, tmp_path)
    assert counts["fetched"] == EXPECTED_FETCHED
    assert counts["blocked"] == 1
    assert counts["queued"] == 0
    hits = site.page_hits()
    # Robots blocked page was never requested
    assert "/private/x" not in hits
    assert "/img.png" not in hits
    assert hits["/only-in-sitemap"] == 1
    # Home is hit once more to find the start
    assert hits.pop("/") == 2
    assert set(hits.values()) == {1}


def test_redirects_are_recorded(site, tmp_path):
    crawl(site, tmp_path)
    db = sqlite3.connect(str(tmp_path / config.CRAWL_DB_NAME))
    rows = dict(db.execute(
        "SELECT u.url, p.redirect_to FROM pages p JOIN urls u ON u.id = p.url_id "
        "WHERE p.redirect_to != ''"
    ))
    assert rows == {
        site.base + "/old": site.base + "/p/1",
        site.base + "/loop-a": site.base + "/loop-b",
        site.base + "/loop-b": site.base + "/loop-a",
    }


def test_finished_crawl_is_frozen(site, tmp_path):
    first = crawl(site, tmp_path, minutes=0.25 / 60, gap=0.03)
    assert 0 < first["fetched"] < EXPECTED_FETCHED
    hits_before = sum(site.hits.values())
    # Out of time counts as finished
    second = crawl(site, tmp_path)
    assert second["fetched"] == first["fetched"]
    assert sum(site.hits.values()) == hits_before


def test_kill_and_resume_loses_nothing(site, tmp_path):
    code = (
        "import asyncio, sys; from pathlib import Path;"
        "from seo_intel.crawl import crawl_sites;"
        "asyncio.run(crawl_sites([sys.argv[1]], Path(sys.argv[2]), 1.0, 1000, 0.03))"
    )
    proc = subprocess.Popen([sys.executable, "-c", code, site.base, str(tmp_path)])
    time.sleep(0.8)
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    db = sqlite3.connect(str(tmp_path / config.CRAWL_DB_NAME))
    done_before = db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    db.close()
    assert 0 < done_before < EXPECTED_FETCHED

    counts = crawl(site, tmp_path)
    assert counts["fetched"] == EXPECTED_FETCHED
    assert counts["queued"] == 0
    hits = site.page_hits()
    hits.pop("/")
    # Only requests in flight at the kill repeat
    repeats = sum(n - 1 for n in hits.values())
    assert repeats <= config.WORKERS_PER_SITE


def test_host_limiter_spaces_requests():
    async def run():
        limiter = HostLimiter(0.05)
        loop = asyncio.get_running_loop()
        times = []

        async def one():
            await limiter.wait()
            times.append(loop.time())

        await asyncio.gather(*(one() for _ in range(8)))
        return sorted(times)

    times = asyncio.run(run())
    gaps = [b - a for a, b in zip(times, times[1:])]
    # Timers may wake a millisecond early
    assert min(gaps) >= 0.045


def test_sitemap_locs():
    body = b"<urlset><url><loc> https://a.com/x?a=1&amp;b=2 </loc></url>"
    body += b"<url><loc><![CDATA[https://a.com/y]]></loc></url></urlset>"
    assert sitemap_locs(body) == ["https://a.com/x?a=1&b=2", "https://a.com/y"]
