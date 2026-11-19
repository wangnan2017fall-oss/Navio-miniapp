#!/usr/bin/env python3
"""A fixed-upstream Maven download cache, bound only to 127.0.0.1:18082.

No URL, upstream, or bind-address arguments are accepted. curl uses its default
TLS verification and ignores proxy environment variables and user curl config.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote, unquote_to_bytes, urlsplit


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT.parent / ".local-runtime" / "http-maven-cache"
UPSTREAM = "https://repo.maven.apache.org/maven2/"
HOST, PORT = "127.0.0.1", 18082
REQUEST_SECONDS = 60
NEGATIVE_SECONDS = 30
METADATA_SECONDS = 60
PART = re.compile(r"[A-Za-z0-9_@+.-]+\Z")
DOWNLOADS = threading.BoundedSemaphore(8)
NEGATIVES: dict = {}
NEGATIVE_GUARD = threading.Lock()


class FetchError(Exception):
    def __init__(self, status: int = 502) -> None:
        self.status = status


class PathLocks:
    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.entries: dict = {}

    @contextmanager
    def acquire(self, key: str, deadline: float):
        with self.guard:
            entry = self.entries.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        acquired = False
        try:
            acquired = entry[0].acquire(timeout=max(0, deadline - time.monotonic()))
            if not acquired:
                raise FetchError()
            yield
        finally:
            if acquired:
                entry[0].release()
            with self.guard:
                entry[1] -= 1
                if entry[1] == 0:
                    self.entries.pop(key, None)


LOCKS = PathLocks()


def relative_path(target: str) -> str:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Only repository-relative paths are accepted")
    raw = parsed.path
    if not raw.startswith("/") or raw.startswith("//") or re.search(r"%(?:2f|5c)", raw, re.I):
        raise ValueError("Invalid repository path")
    decoded = unquote_to_bytes(raw[1:]).decode("ascii", errors="strict")
    pieces = decoded.split("/")
    if not decoded or len(decoded) > 1024 or any(
        not PART.fullmatch(piece) or piece in (".", "..") for piece in pieces
    ):
        raise ValueError("Invalid Maven path segment")
    return "/".join(pieces)


def destination(relative: str) -> Path:
    root = CACHE.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Path escapes local cache")
    return target


def negative_hit(relative: str) -> bool:
    now = time.monotonic()
    with NEGATIVE_GUARD:
        expired = [key for key, expires in NEGATIVES.items() if expires <= now]
        for key in expired:
            NEGATIVES.pop(key, None)
        return NEGATIVES.get(relative, 0) > now


def note_missing(relative: str) -> None:
    with NEGATIVE_GUARD:
        if len(NEGATIVES) >= 4096:
            NEGATIVES.pop(next(iter(NEGATIVES)), None)
        NEGATIVES[relative] = time.monotonic() + NEGATIVE_SECONDS


def cache_fresh(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name.startswith("maven-metadata"):
        return time.time() - path.stat().st_mtime < METADATA_SECONDS
    return True


def artifact(relative: str, deadline: float) -> Path:
    target = destination(relative)
    with LOCKS.acquire(relative, deadline):
        if cache_fresh(target):
            return target
        if negative_hit(relative):
            raise FetchError(404)
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not DOWNLOADS.acquire(timeout=max(0, remaining)):
            raise FetchError()
        temporary = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Re-check resolved containment after directory creation. Temporary
            # bytes are never visible at a final Maven artifact URL.
            target = destination(relative)
            fd, name = tempfile.mkstemp(prefix=".download-", dir=str(target.parent))
            os.close(fd)
            temporary = Path(name)
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                raise FetchError()
            maximum = min(50, max(1, int(remaining - 1)))
            command = [
                "/usr/bin/curl", "-q", "--noproxy", "*", "--fail", "--silent", "--show-error",
                "--proto", "=https", "--connect-timeout", str(min(10, maximum)),
                "--max-time", str(maximum), "--retry", "0", "--output", str(temporary),
                "--write-out", "%{http_code}", UPSTREAM + quote(relative, safe="/+@.-_"),
            ]
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, timeout=max(1, remaining), check=False)
            status = result.stdout.strip()
            if status == "404":
                note_missing(relative)
                raise FetchError(404)
            # Redirects are deliberately not followed to another host.
            if result.returncode != 0 or status != "200":
                raise FetchError()
            os.replace(temporary, target)
            temporary = None
            return target
        except (OSError, subprocess.TimeoutExpired):
            raise FetchError()
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            DOWNLOADS.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "NavioMavenCache/1"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format: str, *args) -> None:
        # Do not log headers, request lines, arbitrary path text, or curl stderr.
        return

    def small_response(self, status: int, body: bytes, head: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if not head:
            self.wfile.write(body)

    def serve(self, head: bool = False) -> None:
        deadline = time.monotonic() + REQUEST_SECONDS
        try:
            if self.path == "/":
                self.small_response(200, b"Local Maven dependency cache\n", head)
                return
            relative = relative_path(self.path)
            target = artifact(relative, deadline)
            with target.open("rb") as source:
                length = os.fstat(source.fileno()).st_size
                self.send_response(200)
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                if not head:
                    while True:
                        block = source.read(256 * 1024)
                        if not block:
                            break
                        self.wfile.write(block)
        except (ValueError, UnicodeError):
            self.small_response(400, b"Invalid Maven repository path\n", head)
        except FetchError as error:
            self.small_response(error.status, b"Artifact not found\n" if error.status == 404 else b"Upstream download failed\n", head)
            # Only an opaque digest is logged, never request/header contents.
            digest = hashlib.sha256(self.path.encode("utf-8", errors="replace")).hexdigest()[:12]
            print(f"download status={error.status} request={digest}", file=sys.stderr, flush=True)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except OSError:
            if not self.wfile.closed:
                try:
                    self.small_response(502, b"Local cache unavailable\n", head)
                except OSError:
                    pass

    def do_GET(self) -> None:
        self.serve()

    def do_HEAD(self) -> None:
        self.serve(head=True)

    def unsupported(self) -> None:
        self.small_response(405, b"Only GET and HEAD are supported\n")

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_CONNECT = unsupported


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        print("cache request failed", file=sys.stderr, flush=True)


def main() -> int:
    if len(sys.argv) != 1:
        print("This service has a fixed loopback address and fixed upstream; arguments are not accepted.", file=sys.stderr)
        return 2
    os.umask(0o077)
    CACHE.mkdir(parents=True, exist_ok=True)
    with Server((HOST, PORT), Handler) as server:
        print(f"Maven dependency cache listening on {HOST}:{PORT}", flush=True)
        server.serve_forever(poll_interval=0.25)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
