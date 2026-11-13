"""Loopback HTTP bridge that lets local AI tools call into the running app.

Requests arrive on a background thread but every operation runs on the Qt main
thread: the HTTP thread queues a job through a signal and waits for its result.
Only 127.0.0.1 is bound, the Host header must name that address, and every
request must carry the per-run bearer token written to the bridge file (which
lives in the user's own profile, next to the library).
"""

from concurrent.futures import Future, TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading

from PySide6.QtCore import QObject, Qt, Signal


MAX_BODY = 8 * 1024 * 1024
DRAIN_LIMIT = 64 * 1024  # Refused requests: read at most this much so Windows shows the error.
SOCKET_TIMEOUT = 15.0
CALL_TIMEOUT = 60.0


class BridgeError(ValueError):
    """A request the app understood but refused; its message is shown to the caller."""


def _write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class BridgeServer(QObject):
    """Serve ``handler(method, params) -> JSON-able`` on the Qt main thread."""

    _job = Signal(object)

    def __init__(self, handler, info_path, parent=None):
        super().__init__(parent)
        self._handler = handler
        self.info_path = Path(info_path)
        self.token = secrets.token_urlsafe(32)
        self.port = None
        self._server = None
        self._thread = None
        # Queued: the slot always runs in this object's (main) thread.
        self._job.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @property
    def running(self):
        return self._server is not None

    def start(self):
        if self._server is not None:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            timeout = SOCKET_TIMEOUT  # A client that stalls mid-request releases its thread.

            def log_message(self, *args):  # Keep stderr quiet; requests may carry user content.
                pass

            def _reply(self, status, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._reply(405, {"error": "Use POST /rpc"})

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    length = None
                refusal = bridge._refuse(self.path, self.headers)
                if refusal is not None:
                    # Drain a small body first: answering while the client is still sending
                    # makes Windows abort the connection instead of showing the error.
                    if length is not None and 0 < length <= DRAIN_LIMIT:
                        self.rfile.read(length)
                    self._reply(*refusal)
                    return
                body = self.rfile.read(length) if length is not None and 0 < length <= MAX_BODY else None
                status, payload = bridge._serve(length, body)
                self._reply(status, payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        self.port = server.server_address[1]
        try:
            _write_atomic(self.info_path, {"port": self.port, "token": self.token, "pid": os.getpid()})
        except OSError:
            server.server_close()
            self.port = None
            raise
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name="lapicero-bridge", daemon=True)
        self._thread.start()

    def stop(self):
        server, self._server = self._server, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        self._thread.join(timeout=5)
        try:  # Leave a newer instance's bridge file alone.
            if json.loads(self.info_path.read_text(encoding="utf-8")).get("token") == self.token:
                self.info_path.unlink()
        except (OSError, ValueError):
            pass

    def _refuse(self, path, headers):
        """HTTP thread: (status, payload) for a request refused before reading its body."""
        if path != "/rpc":
            return 404, {"error": "Not found"}
        if headers.get("Host") not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            return 403, {"error": "Forbidden host"}
        expected = f"Bearer {self.token}".encode()
        if not hmac.compare_digest(headers.get("Authorization", "").encode(), expected):
            return 401, {"error": "Invalid token"}
        return None

    def _serve(self, length, body):
        """HTTP thread: validate an authorized body, then hand the call to the main thread."""
        if length is None:
            return 411, {"error": "Content-Length required"}
        if body is None:
            return 413, {"error": "Request body too large or empty"}
        try:
            request = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError):
            return 400, {"error": "Body must be JSON"}
        if not isinstance(request, dict) or not isinstance(request.get("method"), str) or not isinstance(
                request.get("params", {}), dict):
            return 400, {"error": "Expected {\"method\": str, \"params\": object}"}
        future = Future()
        self._job.emit((request["method"], request.get("params", {}), future))
        try:
            return 200, {"result": future.result(timeout=CALL_TIMEOUT)}
        except FutureTimeout:
            future.cancel()
            return 504, {"error": "Lapicero did not answer in time"}
        except BridgeError as exc:
            return 400, {"error": str(exc)}
        except Exception:  # Never leak internals over the socket.
            return 500, {"error": "Lapicero failed to run the request"}

    def _run(self, job):
        method, params, future = job
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(self._handler(method, params))
        except Exception as exc:
            future.set_exception(exc)
