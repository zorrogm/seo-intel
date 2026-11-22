"""A local site where some pages need JavaScript."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATIC, APP, HYBRID = 200, 12, 10
TEXT = "Tomatoes like deep watering twice a week and plenty of morning sun. " * 8
PADDING = "/* " + "x" * 2500 + " */"


def shell(script_text):
    script = f"{PADDING} document.getElementById('spot').innerHTML = {script_text!r};"
    return f'<div id="spot"></div><script>{script}</script>'


class JsSite:
    def __init__(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, status, body, kind="text/html"):
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path
                if path == "/robots.txt":
                    return self.send(200, "User-agent: *\nAllow: /\n", "text/plain")
                if path == "/":
                    links = [f"/static/{i}" for i in range(STATIC)]
                    links += [f"/app/{i}" for i in range(APP)] + [f"/hybrid/{i}" for i in range(HYBRID)]
                    body = "".join(f'<p><a href="{l}">{l}</a></p>' for l in links)
                    return self.send(200, f"<html><title>Home</title><body>{body}</body></html>")
                kind, _, number = path.strip("/").partition("/")
                title = f"<title>{kind} page {number}</title>"
                if kind == "static":
                    body = f"<p>Static page {number}. {TEXT}</p>"
                elif kind == "app":
                    body = shell(f"<p>App page {number}. {TEXT}</p>")
                elif kind == "hybrid":
                    body = f"<p>Hybrid page {number}. {TEXT}</p>" + shell(f"<p>More. {TEXT}{TEXT}</p>")
                else:
                    return self.send(404, "<html>missing</html>")
                return self.send(200, f"<html><head>{title}</head><body>{body}</body></html>")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
