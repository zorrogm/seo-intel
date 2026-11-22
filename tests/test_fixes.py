import asyncio
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from seo_intel import config
from seo_intel.crawl import crawl_sites
from seo_intel.plan import finalise
from seo_intel.traps import TrapGuard


def test_numbered_pages_are_not_a_filter_trap():
    guard = TrapGuard()
    assert all(guard.check(f"https://a.com/blog/?page={n}") is None for n in range(1, 120))
    mixes = [guard.check(f"https://a.com/shop?color=c{n}&size=m") for n in range(30)]
    assert mixes[: config.MAX_QUERY_VARIANTS_PER_PATH] == [None] * config.MAX_QUERY_VARIANTS_PER_PATH
    assert mixes[-1][0] == "faceted"


class Truthful:
    def check(self, claim):
        return True, claim["value"]


def test_plan_fill_mixes_action_types():
    def action(number, kind, score):
        return {"id": f"a{number}", "type": kind, "score": score, "urls": ["u"],
                "claims": [{"id": f"c{number}", "url": "u", "field": "status", "value": 200}]}

    candidates = [action(n, "merge_301", 0.9) for n in range(1, 31)]
    candidates += [action(n, "add_internal_link", 0.4) for n in range(31, 36)]
    plan = finalise(candidates, [], Truthful())
    kinds = Counter(a["type"] for a in plan["actions"])
    assert kinds["add_internal_link"] == 5
    # The quota relaxes to fill all 25 places
    assert len(plan["actions"]) == config.PLAN_ACTIONS


def test_rate_limited_pages_are_retried_not_lost(tmp_path):
    refused = Counter()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path
            if path.startswith("/p/") and refused[path] < 1:
                # First visit to each page is refused
                refused[path] += 1
                self.send_response(429)
                self.send_header("Retry-After", "0")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/":
                body = "".join(f'<a href="/p/{i}">p</a>' for i in range(6))
            elif path.startswith("/p/"):
                body = f"<p>page {path}</p>"
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data = f"<html><body>{body}</body></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    old_retries, config.FETCH_RETRIES = config.FETCH_RETRIES, 0
    old_cap, config.MAX_BACKOFF_GAP_SECONDS = config.MAX_BACKOFF_GAP_SECONDS, 0.01
    try:
        asyncio.run(crawl_sites([base], tmp_path, 1.0, 100, 0.001))
    finally:
        config.FETCH_RETRIES, config.MAX_BACKOFF_GAP_SECONDS = old_retries, old_cap
        server.shutdown()
        server.server_close()
    import sqlite3
    db = sqlite3.connect(str(tmp_path / config.CRAWL_DB_NAME))
    statuses = Counter(row[0] for row in db.execute(
        "SELECT p.status FROM pages p JOIN urls u ON u.id = p.url_id WHERE u.url LIKE '%/p/%'"))
    assert statuses == {200: 6}
