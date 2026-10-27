"""Tiny localhost receiver for the browser extension. Binds to 127.0.0.1 only.

Accepts POST /capture with JSON {url, title, text}. Requests that carry a web-page Origin are rejected, so
ordinary websites cannot push data into the queue; only the extension (chrome-extension:// origin) or local
tools without an Origin header can. Captures go to a review queue and are never saved automatically.
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import db
from .capture import MAX_TEXT, blocked_reason, capture_blocked, enqueue

log = logging.getLogger(__name__)
MAX_BODY = 2_000_000
ALLOWED_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://", "edge-extension://")


def make_handler(db_path: str | Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RivianFinderCapture/1.0"

        def log_message(self, fmt, *args):  # keep request bodies/URLs out of logs
            log.debug("capture server: %s", self.command)

        def _send(self, code: int, payload: dict):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            origin = self.headers.get("Origin", "")
            if origin.startswith(ALLOWED_ORIGIN_PREFIXES):
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            self.wfile.write(body)

        def _origin_ok(self) -> bool:
            origin = self.headers.get("Origin")
            return origin is None or origin.startswith(ALLOWED_ORIGIN_PREFIXES)

        def do_OPTIONS(self):  # noqa: N802
            if not self._origin_ok():
                self._send(403, {"error": "origin not allowed"})
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", ""))
            self.send_header("Access-Control-Allow-Methods", "POST, GET")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") == "/health":
                self._send(200, {"ok": True, "app": "rivian-finder"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") != "/capture":
                self._send(404, {"error": "not found"})
                return
            if not self._origin_ok():
                self._send(403, {"error": "origin not allowed"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                self._send(413, {"error": "body missing or too large"})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._send(400, {"error": "invalid JSON"})
                return
            url = str(payload.get("url") or "")[:2000]
            if capture_blocked(url):
                self._send(422, {"error": "Capture is disabled for this site. "
                                          + (blocked_reason(url) or "").replace("**", "")})
                return
            text = str(payload.get("text") or "")[:MAX_TEXT]
            title = str(payload.get("title") or "")[:500]
            image = str(payload.get("image") or "")[:2000]
            conn = db.connect(db_path)
            try:
                cid = enqueue(conn, "extension", url, title, text, image)
            finally:
                conn.close()
            self._send(200, {"ok": True, "id": cid, "message": "Captured. Review it in MotorSift → Sources → Assisted capture."})

    return Handler


class CaptureServer:
    def __init__(self, db_path: str | Path, host: str = "127.0.0.1", port: int = 8765):
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("capture server must bind to localhost")
        self.httpd = ThreadingHTTPServer((host, port), make_handler(db_path))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="capture-server")

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def start(self) -> "CaptureServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
