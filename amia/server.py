"""Tiny local web server (standard library only). Binds to 127.0.0.1 so nothing is reachable from outside."""
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from .extractors import ExtractorError, OllamaExtractor
from .pipeline import ENGINES, analyze
from .report import to_markdown
from .store import Store, ValidationError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_BODY = 5 * 1024 * 1024


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AMIA/" + __version__

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json", extra=None):
            data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if "text" in ctype or "json" in ctype else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _err(self, code, msg):
            self._send(code, {"error": msg})

        def _json_body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("Request too large (max 5 MB)")
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                raise ValueError("Body must be valid JSON")
            if not isinstance(data, dict):
                raise ValueError("Body must be a JSON object")
            return data

        def do_GET(self):
            u = urlparse(self.path)
            try:
                if u.path in ("/", "/index.html"):
                    with open(os.path.join(ROOT, "static", "index.html"), "rb") as f:
                        return self._send(200, f.read(), "text/html")
                if u.path == "/api/health":
                    o = OllamaExtractor()
                    names = o.installed()
                    ok, msg = o.available()
                    return self._send(200, {"version": __version__, "ollama": ok, "ollama_message": msg,
                                            "ollama_running": names is not None, "models": names or [],
                                            "model": o.model, "engines": list(ENGINES)})
                if u.path == "/api/sample":
                    with open(os.path.join(ROOT, "samples", "sample_meeting.txt"), encoding="utf-8") as f:
                        return self._send(200, {"transcript": f.read(), "title": "Project Falcon weekly sync",
                                                "meeting_date": "2026-11-17"})
                if u.path == "/api/runs":
                    return self._send(200, store.list_runs())
                m = re.fullmatch(r"/api/runs/([0-9a-f]+)", u.path)
                if m:
                    r = store.get_run(m[1])
                    return self._send(200, r) if r else self._err(404, "Run not found")
                m = re.fullmatch(r"/api/runs/([0-9a-f]+)/export", u.path)
                if m:
                    r = store.get_run(m[1])
                    if not r:
                        return self._err(404, "Run not found")
                    fmt = parse_qs(u.query).get("format", ["md"])[0]
                    if fmt == "json":
                        return self._send(200, r, extra={"Content-Disposition": f"attachment; filename=amia-{m[1]}.json"})
                    return self._send(200, to_markdown(r), "text/markdown",
                                      {"Content-Disposition": f"attachment; filename=amia-{m[1]}.md"})
                self._err(404, "Not found")
            except Exception as e:  # never leak a stack trace to the browser
                self._err(500, f"Internal error: {e}")

        def do_POST(self):
            u = urlparse(self.path)
            try:
                if u.path == "/api/analyze":
                    d = self._json_body()
                    text = d.get("transcript")
                    if not isinstance(text, str) or not text.strip():
                        return self._err(400, "transcript is required")
                    if d.get("meeting_date") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d["meeting_date"])):
                        return self._err(400, "meeting_date must be YYYY-MM-DD")
                    model = d.get("model") or None
                    if model is not None and not re.fullmatch(r"[\w.:/-]{1,80}", str(model)):
                        return self._err(400, "invalid model name")
                    try:
                        report = analyze(text, d.get("meeting_date") or None, d.get("engine") or "auto",
                                         str(d.get("title") or "")[:120], model=model)
                    except ExtractorError as e:
                        return self._err(502, str(e))
                    except ValueError as e:
                        return self._err(400, str(e))
                    return self._send(200, store.create_run(report))
                m = re.fullmatch(r"/api/runs/([0-9a-f]+)/items/(i\d+)/correct", u.path)
                if m:
                    try:
                        return self._send(200, store.add_correction(m[1], m[2], self._json_body()))
                    except KeyError as e:
                        return self._err(404, str(e).strip("'"))
                    except ValidationError as e:
                        return self._err(400, str(e))
                self._err(404, "Not found")
            except ValueError as e:
                self._err(400, str(e))
            except Exception as e:
                self._err(500, f"Internal error: {e}")

    return Handler


def main():
    host, port = "127.0.0.1", int(os.environ.get("AMIA_PORT", "8765"))
    db = os.environ.get("AMIA_DB", os.path.join(ROOT, "data", "amia.db"))
    os.makedirs(os.path.dirname(db), exist_ok=True)
    srv = ThreadingHTTPServer((host, port), make_handler(Store(db)))
    print(f"AMIA running at http://{host}:{port}  (local only - transcripts never leave this computer)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
