"""A tiny local website for crawler tests."""
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGES = 30


class FakeSite:
    def __init__(self):
        self.hits = Counter()
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, status, body=b"", kind="text/html", location=None):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                if location:
                    self.send_header("Location", location)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path
                site.hits[path] += 1
                if path == "/robots.txt":
                    text = "User-agent: *\nDisallow: /private/\nSitemap: /sitemap.xml\n"
                    return self.send(200, text.encode(), "text/plain")
                if path == "/sitemap.xml":
                    xml = f"<urlset><url><loc>{site.base}/only-in-sitemap</loc></url></urlset>"
                    return self.send(200, xml.encode(), "application/xml")
                if path == "/":
                    links = "".join(f'<a href="/p/{i}">p{i}</a>' for i in range(1, PAGES + 1))
                    extra = '<a href="/old">old</a><a href="/loop-a">loop</a>'
                    extra += '<a href="/private/x">secret</a><a href="/img.png">img</a>'
                    extra += '<a href="https://elsewhere.example/">out</a>'
                    return self.send(200, f"<html><body>{links}{extra}</body></html>".encode())
                if path == "/old":
                    return self.send(301, location="/p/1")
                if path == "/loop-a":
                    return self.send(302, location="/loop-b")
                if path == "/loop-b":
                    return self.send(302, location="/loop-a")
                if path.startswith("/p/") or path == "/only-in-sitemap":
                    return self.send(200, f'<html><a href="/">home</a> {path}</html>'.encode())
                return self.send(404, b"<html>not found</html>")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def page_hits(self):
        """Hits on crawlable pages only."""
        skip = ("/robots.txt", "/sitemap.xml")
        return {p: n for p, n in self.hits.items() if p not in skip}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
