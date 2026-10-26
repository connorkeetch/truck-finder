"""Private deployment: all app paths authenticate before reaching the loopback upstream."""
from __future__ import annotations

import base64
import hashlib
import http.client
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_railway_uses_proxy_health_and_one_durable_database():
    config = tomllib.loads((ROOT / "railway.toml").read_text(encoding="utf-8"))
    assert config["build"]["builder"] == "DOCKERFILE"
    assert config["deploy"]["healthcheckPath"] == "/_stcore/health"
    assert config["deploy"]["numReplicas"] == 1
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM caddy:2.11.7-alpine AS caddy" in dockerfile
    assert "RIVIAN_FINDER_CLOUD=1" in dockerfile
    assert "RIVIAN_FINDER_DATA_DIR=/data" in dockerfile
    assert "tzdata" in dockerfile
    assert "EXPOSE 8501" not in dockerfile
    assert (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()[0] == "**"


@pytest.mark.parametrize("missing", ["TRUCK_FINDER_PASSWORD_HASH", "TRUCK_FINDER_PROXY_SECRET"])
def test_entrypoint_fails_closed_without_credentials(missing):
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if os.name == "nt" and git_bash.exists() else shutil.which("bash")
    if not bash:
        pytest.skip("bash is unavailable on this test host")
    env = {**os.environ, "TRUCK_FINDER_PASSWORD_HASH": "test-placeholder", "TRUCK_FINDER_PROXY_SECRET": "test-placeholder"}
    env.pop(missing, None)
    result = subprocess.run([bash, (ROOT / "docker-entrypoint.sh").as_posix()], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 64
    assert missing in result.stderr


@pytest.fixture(scope="module")
def caddy_binary():
    binary = os.environ.get("CADDY_BIN") or shutil.which("caddy")
    if not binary:
        pytest.skip("Set CADDY_BIN to run the actual Caddy authentication integration test")
    return binary


@pytest.fixture(scope="module")
def proxy(caddy_binary):
    password, token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    result = subprocess.run([caddy_binary, "hash-password", "--algorithm", "bcrypt", "--bcrypt-cost", "4"],
                            input=(password + "\n").encode(), capture_output=True, check=True, timeout=10)
    requests = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            requests.append({"path": self.path, "authorization": self.headers.get("Authorization"),
                             "user": self.headers.get("X-Truck-Finder-User"),
                             "token": self.headers.get("X-Truck-Finder-Token")})
            if self.headers.get("Upgrade", "").lower() == "websocket":
                key = self.headers["Sec-WebSocket-Key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", base64.b64encode(hashlib.sha1(key.encode()).digest()).decode())
                self.end_headers()
                self.close_connection = True
                return
            body = b"ok" if self.path == "/_stcore/health" else b"authenticated app response"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "PORT": str(port), "TRUCK_FINDER_USER": "validation-user",
           "TRUCK_FINDER_PASSWORD_HASH": result.stdout.decode().strip(), "TRUCK_FINDER_PROXY_SECRET": token}
    # Use the production routes with only the local test upstream/listener changed.
    text = (ROOT / "Caddyfile").read_text(encoding="utf-8")
    text = text.replace(":{$PORT:8080}", "http://127.0.0.1:{$PORT:8080}")
    text = text.replace("127.0.0.1:8501", f"127.0.0.1:{upstream.server_port}")
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "Caddyfile"
        path.write_text(text, encoding="utf-8")
        subprocess.run([caddy_binary, "validate", "--config", str(path), "--adapter", "caddyfile"],
                       env=env, capture_output=True, check=True, timeout=10)
        process = subprocess.Popen([caddy_binary, "run", "--config", str(path), "--adapter", "caddyfile"],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            for _ in range(200):
                if process.poll() is not None:
                    pytest.fail("Caddy stopped before serving requests")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.1):
                        break
                except OSError:
                    time.sleep(.05)
            else:
                pytest.fail("Caddy did not start")
            yield port, password, token, requests
        finally:
            process.terminate()
            process.wait(timeout=10)
            upstream.shutdown()
            upstream.server_close()


def request(proxy, path, *, authenticated=False, method="GET", websocket=False):
    port, password, _, _ = proxy
    headers = {"X-Truck-Finder-User": "forged-user", "X-Truck-Finder-Token": "forged-token"}
    if authenticated:
        headers["Authorization"] = "Basic " + base64.b64encode(("validation-user:" + password).encode()).decode()
    if websocket:
        headers.update(Upgrade="websocket", Connection="Upgrade")
        headers["Sec-WebSocket-Key"] = base64.b64encode(secrets.token_bytes(16)).decode()
        headers["Sec-WebSocket-Version"] = "13"
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read() if response.status != 101 else b""
        return response.status, dict(response.getheaders()), body
    finally:
        connection.close()


@pytest.mark.parametrize("path", ["/", "/inventory", "/static/photos/private.jpg", "/_stcore/media/private",
                                   "/_stcore/stream", "/_stcore/health/", "/_stcore/health/extra"])
def test_app_static_media_and_stream_require_authentication(proxy, path):
    before = len(proxy[3])
    status, headers, _ = request(proxy, path)
    assert status == 401
    assert any(name.lower() == "www-authenticate" for name in headers)
    assert len(proxy[3]) == before


def test_only_exact_get_head_health_is_public(proxy):
    assert request(proxy, "/_stcore/health")[0] == 200
    assert request(proxy, "/_stcore/health", method="HEAD")[0] == 200
    assert request(proxy, "/_stcore/health", method="POST")[0] == 401


def test_authenticated_proxy_sets_trusted_headers_and_keeps_token_private(proxy):
    status, headers, body = request(proxy, "/inventory", authenticated=True)
    assert status == 200
    assert proxy[3][-1]["user"] == "validation-user"
    assert proxy[3][-1]["token"] == proxy[2]
    assert proxy[3][-1]["authorization"] is None
    assert proxy[2] not in repr(headers) and proxy[2].encode() not in body


def test_websocket_upgrade_is_authenticated(proxy):
    assert request(proxy, "/_stcore/stream", websocket=True)[0] == 401
    assert request(proxy, "/_stcore/stream", authenticated=True, websocket=True)[0] == 101
    assert proxy[3][-1]["token"] == proxy[2]
