"""Static file server plus one POST endpoint for the operator inbox."""

import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(ROOT, "artifacts", "run", "inbox.json")


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

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    print("serving on http://localhost:8000/ui/index.html")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
