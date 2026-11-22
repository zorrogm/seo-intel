"""A local site full of crawler traps."""
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

FILLER = "This paragraph talks about gardening tools and how to keep them sharp all year. "
MISSING = "<html><title>Oops</title><body><p>We could not locate the thing you were looking for on this website today sorry.</p></body></html>"
COLORS = ["red", "blue", "green", "black", "white"]
SIZES = ["s", "m", "l", "xl", "xxl"]


def page(title, body, head=""):
    return f"<html><head><title>{title}</title>{head}</head><body>{body}</body></html>"


class TrickySite:
    def __init__(self):
        self.hits = Counter()
        self.not_modified = 0
        self.changed = False
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, status, body="", kind="text/html", headers=None):
                data = body.encode()
                etag = f'"{hash(body) & 0xffffffff:x}"'
                if status == 200 and self.headers.get("If-None-Match") == etag:
                    site.not_modified += 1
                    status, data = 304, b""
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                if status == 200:
                    self.send_header("ETag", etag)
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                site.hits[self.path] += 1
                parts = urlsplit(self.path)
                path, query = parts.path, parse_qs(parts.query)
                if path == "/robots.txt":
                    return self.send(200, "User-agent: *\nAllow: /\n", "text/plain")
                if path == "/sitemap.xml":
                    return self.send(404, "")
                if path == "/":
                    hrefs = [
                        "/cal/2025/01/", "/shop?color=red&size=m", "/loop/x", "/meta", "/js",
                        "/gone", "/empty", "/gone2", "/login;jsessionid=ABC123?sid=999",
                        "/a?utm_source=news", "/nofollow-page", "/xrobots", "/canon-a",
                        "/canon-d", "/b", "/c",
                    ]
                    if site.changed:
                        hrefs.append("/new-page")
                    links = "".join(f'<p><a href="{h}">{h}</a></p>' for h in hrefs)
                    links += '<p><a rel="nofollow" href="/hidden1">hidden</a></p>'
                    return self.send(200, page("Home", links + f"<p>{FILLER}</p>"))
                if path.startswith("/cal/"):
                    _, _, year, month = path.rstrip("/").split("/")
                    year, month = int(year), int(month) + 1
                    if month > 12:
                        year, month = year + 1, 1
                    nxt = f"/cal/{year}/{month:02d}/"
                    return self.send(200, page("Calendar", f'<p><a href="{nxt}">next</a> {FILLER}</p>'))
                if path == "/shop":
                    links = "".join(
                        f'<a href="/shop?color={c}&size={s}">{c} {s}</a> ' for c in COLORS for s in SIZES
                    )
                    return self.send(200, page("Shop", f"<p>{links}</p><p>{FILLER} {sorted(query.items())}</p>"))
                if path.startswith("/loop/"):
                    return self.send(200, page("Loop", f'<p><a href="{path}/loop/x">deeper</a> {FILLER}</p>'))
                if path == "/meta":
                    head = '<meta http-equiv="refresh" content="0; url=/a">'
                    return self.send(200, page("Moved", "<p>Moved.</p>", head))
                if path == "/js":
                    return self.send(200, page("", '<script>window.location.href = "/a";</script>'))
                if path == "/gone":
                    return self.send(200, page("Page not found", "<h1>Page not found</h1><p>Sorry.</p>"))
                if path == "/empty":
                    return self.send(200, "<html><body></body></html>")
                if path == "/login":
                    return self.send(200, page("Login", f"<p>Sign in here. {FILLER}</p>"))
                if path == "/nofollow-page":
                    head = '<meta name="robots" content="nofollow">'
                    return self.send(200, page("Quiet", f'<p><a href="/hidden2">x</a> {FILLER} quiet page</p>', head))
                if path == "/xrobots":
                    body = page("Header rules", f"<p>{FILLER} header page</p>")
                    return self.send(200, body, headers={"X-Robots-Tag": "noindex"})
                if path in ("/canon-a", "/canon-b", "/canon-c", "/canon-d"):
                    target = {"/canon-a": "/canon-b", "/canon-b": "/canon-c",
                              "/canon-c": "/canon-c", "/canon-d": "/really-gone"}[path]
                    head = f'<link rel="canonical" href="{target}">'
                    links = '<a href="/canon-b">b</a> <a href="/canon-c">c</a> <a href="/really-gone">g</a>'
                    return self.send(200, page(f"Canon {path}", f"<p>{links} {FILLER} {path} text</p>", head))
                if path == "/really-gone":
                    return self.send(404, page("Gone", "<p>Gone.</p>"))
                if path == "/a":
                    title = "Sharpening guide updated" if site.changed else "Sharpening guide"
                    return self.send(200, page(title, f"<h1>Sharpening</h1><p>{FILLER * 3}</p>"))
                if path == "/b":
                    if site.changed:
                        return self.send(404, page("Gone", "<p>Gone.</p>"))
                    return self.send(200, page("Pruning guide", f"<p>Pruning roses in spring. {FILLER}</p>"))
                if path == "/c":
                    if site.changed:
                        return self.send(301, "", headers={"Location": "/a"})
                    return self.send(200, page("Watering guide", f"<p>Watering in summer heat. {FILLER}</p>"))
                if path == "/new-page" and site.changed:
                    return self.send(200, page("Compost guide", f"<p>Making compost at home. {FILLER}</p>"))
                # Unknown URLs answer 200, a soft 404
                return self.send(200, MISSING)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def hit_paths(self, prefix):
        return [p for p in self.hits if p.startswith(prefix)]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
