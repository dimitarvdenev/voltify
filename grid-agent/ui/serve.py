"""Static file server plus one POST endpoint for the operator inbox."""

import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_DIR = os.path.join(ROOT, "artifacts", "run")
INBOX = os.path.join(RUN_DIR, "inbox.json")
STEPS = os.path.join(RUN_DIR, "steps.json")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))


def ensure_run_files():
    """Create empty UI artifacts so polling is quiet before the agent starts."""
    os.makedirs(RUN_DIR, exist_ok=True)
    if not os.path.exists(STEPS):
        with open(STEPS, "w") as f:
            json.dump([], f)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_POST(self):
        if self.path != "/inbox":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        os.makedirs(os.path.dirname(INBOX), exist_ok=True)
        try:
            with open(INBOX) as f:
                items = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            items = []
        items.append({"text": body["text"]})
        with open(INBOX, "w") as f:
            json.dump(items, f)
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if self.path.split("?", 1)[0] == "/artifacts/run/steps.json":
            ensure_run_files()
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    ensure_run_files()
    print(f"serving on http://localhost:{PORT}/ui/index.html")
    HTTPServer((HOST, PORT), Handler).serve_forever()
