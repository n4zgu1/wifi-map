from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlsplit

from .core import Store, geojson


def serve(db_path: Path, port: int):
    token = secrets.token_urlsafe(32)
    static = Path(__file__).with_name("static")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log authorization tokens or request paths.

        def send(self, body: bytes, content_type: str, status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://tile.openstreetmap.org; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # Local-only server plus Host check prevent DNS-rebinding access.
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                self.send(b"Invalid host", "text/plain", 403)
                return
            url = urlsplit(self.path)
            if url.path.startswith("/api/"):
                supplied = self.headers.get("Authorization", "")
                if not hmac.compare_digest(supplied.encode("utf-8"), ("Bearer " + token).encode("utf-8")):
                    self.send(b"Unauthorized", "text/plain", 401)
                    return
                store = Store(db_path)
                try:
                    if url.path == "/api/sessions":
                        data = store.sessions()
                    elif url.path in ("/api/points", "/api/export"):
                        sid = parse_qs(url.query).get("session", [""])[0]
                        points = store.points(sid)
                        data = geojson(points) if url.path == "/api/export" else points
                    else:
                        self.send(b"Not found", "text/plain", 404)
                        return
                    self.send(json.dumps(data).encode(), "application/json; charset=utf-8")
                finally:
                    store.close()
                return
            assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "application/javascript"),
                      "/style.css": ("style.css", "text/css")}
            if url.path not in assets:
                self.send(b"Not found", "text/plain", 404)
                return
            filename, content_type = assets[url.path]
            self.send((static / filename).read_bytes(), content_type + "; charset=utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Lokale Karte: http://127.0.0.1:{port}/#token={token}", flush=True)
    print("Der Link enthält einen Zugangsschlüssel. Nicht weitergeben. Beenden: Strg+C.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
