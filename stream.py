#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import providers
from providers import ResolvedStream, StreamError, header_int, http_request, resolve


CHUNK_SIZE = 256 * 1024


class RangeCache:
    def __init__(self, path: Path):
        self.path = path
        self.intervals: list[tuple[int, int]] = []
        self.lock = threading.Lock()
        self.path.touch()

    def contains(self, start: int, end: int) -> bool:
        with self.lock:
            return any(a <= start and end <= b for a, b in self.intervals)

    def add(self, start: int, end: int) -> None:
        if end < start:
            return
        with self.lock:
            merged: list[tuple[int, int]] = []
            new_start, new_end = start, end
            for a, b in self.intervals:
                if b + 1 < new_start:
                    merged.append((a, b))
                elif new_end + 1 < a:
                    merged.append((new_start, new_end))
                    new_start, new_end = a, b
                else:
                    new_start, new_end = min(new_start, a), max(new_end, b)
            merged.append((new_start, new_end))
            self.intervals = merged

    def write_at(self, offset: int, data: bytes) -> None:
        with self.lock:
            with self.path.open("r+b") as f:
                f.seek(offset)
                f.write(data)
        self.add(offset, offset + len(data) - 1)

    def send(self, wfile, start: int, end: int) -> None:
        remaining = end - start + 1
        with self.path.open("rb") as f:
            f.seek(start)
            while remaining:
                data = f.read(min(CHUNK_SIZE, remaining))
                if not data:
                    break
                wfile.write(data)
                remaining -= len(data)


def parse_range(value: Optional[str], length: Optional[int]) -> Optional[tuple[int, int]]:
    if not value:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match:
        return None
    left, right = match.groups()
    if not left and not right:
        return None
    if not left:
        if length is None:
            return None
        size = int(right)
        return max(0, length - size), length - 1
    start = int(left)
    end = int(right) if right else (length - 1 if length is not None else None)
    if end is None or start > end or (length is not None and start >= length):
        return None
    return start, min(end, length - 1) if length is not None else end


def make_handler(stream: ResolvedStream, cache: RangeCache, quiet: bool):
    class ProxyHandler(BaseHTTPRequestHandler):
        server_version = "StreamCLI/0.1"

        def log_message(self, fmt, *args):
            if not quiet:
                print(f"[proxy] {self.address_string()} {fmt % args}")

        def do_HEAD(self):
            self.serve(head_only=True)

        def do_GET(self):
            self.serve(head_only=False)

        def serve(self, head_only: bool) -> None:
            if urllib.parse.urlparse(self.path).path != "/video":
                self.send_error(404)
                return
            requested = parse_range(self.headers.get("Range"), stream.length)
            if requested and cache.contains(*requested):
                self.send_cached(*requested, head_only=head_only)
                return
            if requested and not stream.supports_range:
                self.send_error(416, "Provider does not support seeking outside cached bytes")
                return
            try:
                self.fetch_and_send(requested, head_only=head_only)
            except BrokenPipeError:
                pass
            except urllib.error.HTTPError as exc:
                self.send_error(exc.code, f"Upstream error: {exc.reason}")
            except Exception as exc:
                self.send_error(502, f"Upstream error: {exc}")

        def common_headers(self, status: int, body_length: Optional[int] = None, content_range: Optional[str] = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", stream.content_type)
            if stream.supports_range:
                self.send_header("Accept-Ranges", "bytes")
            if body_length is not None:
                self.send_header("Content-Length", str(body_length))
            if content_range:
                self.send_header("Content-Range", content_range)
            self.end_headers()

        def send_cached(self, start: int, end: int, head_only: bool) -> None:
            total = stream.length if stream.length is not None else "*"
            self.common_headers(206, end - start + 1, f"bytes {start}-{end}/{total}")
            if not head_only:
                cache.send(self.wfile, start, end)

        def fetch_and_send(self, requested: Optional[tuple[int, int]], head_only: bool) -> None:
            headers = dict(stream.headers)
            if requested:
                start, end = requested
                headers["Range"] = f"bytes={start}-{end}"
            else:
                start, end = 0, stream.length - 1 if stream.length is not None else None

            with http_request(stream.url, headers) as response:
                upstream_length = header_int(response.headers, "Content-Length")
                if requested:
                    if response.status != 206:
                        self.send_error(416, "Provider ignored byte range")
                        return
                    body_length = end - start + 1
                    total = stream.length if stream.length is not None else "*"
                    self.common_headers(206, body_length, f"bytes {start}-{end}/{total}")
                else:
                    body_length = stream.length or upstream_length
                    self.common_headers(200, body_length)

                if head_only:
                    return

                offset = start
                while True:
                    data = response.read(CHUNK_SIZE)
                    if not data:
                        break
                    self.wfile.write(data)
                    cache.write_at(offset, data)
                    offset += len(data)

    return ProxyHandler


def find_vlc(custom_path: Optional[str]) -> str:
    candidates: list[str] = []
    if custom_path:
        candidates.append(custom_path)
    if sys.platform == "darwin":
        candidates += ["/Applications/VLC.app/Contents/MacOS/VLC"]
    if sys.platform.startswith("win"):
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if root:
                candidates.append(str(Path(root) / "VideoLAN" / "VLC" / "vlc.exe"))
    path_vlc = shutil.which("vlc")
    if path_vlc:
        candidates.append(path_vlc)
    for path in candidates:
        if path and Path(path).exists():
            return path
    raise StreamError("VLC tidak ditemukan. Install VLC atau pakai --vlc-path /path/to/vlc.")


def start_server(stream: ResolvedStream, cache: RangeCache, port: Optional[int], quiet: bool):
    server = ThreadingHTTPServer(("127.0.0.1", port or 0), make_handler(stream, cache, quiet))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}/video"


def run(args) -> int:
    if args.list_providers:
        print("\n".join(providers.SUPPORTED_PROVIDERS))
        return 0

    stream = resolve(args.url)
    if not args.quiet:
        size = f"{stream.length} bytes" if stream.length is not None else "unknown size"
        seeking = "range" if stream.supports_range else "no range"
        print(f"[streamcli] {stream.provider}: {stream.content_type}, {size}, {seeking}")

    temp_dir = Path(tempfile.mkdtemp(prefix="streamcli_"))
    server = None

    def cleanup():
        if server:
            server.shutdown()
            server.server_close()
        if not args.keep_cache:
            shutil.rmtree(temp_dir, ignore_errors=True)
        elif not args.quiet:
            print(f"[streamcli] cache kept: {temp_dir}")

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    cache = RangeCache(temp_dir / "video.cache")
    server, local_url = start_server(stream, cache, args.port, args.quiet)
    vlc_path = find_vlc(args.vlc_path)
    if not args.quiet:
        print(f"[streamcli] opening VLC: {local_url}")
    vlc = subprocess.Popen([vlc_path, local_url])
    try:
        while vlc.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        vlc.terminate()
    return vlc.returncode or 0


def self_test() -> None:
    assert parse_range("bytes=0-9", 100) == (0, 9)
    assert parse_range("bytes=10-", 100) == (10, 99)
    assert parse_range("bytes=-5", 100) == (95, 99)
    with tempfile.TemporaryDirectory() as d:
        cache = RangeCache(Path(d) / "cache.bin")
        cache.write_at(5, b"world")
        cache.write_at(0, b"hello")
        assert cache.contains(0, 9)
        assert cache.intervals == [(0, 9)]
    providers.self_test()
    print("self-test ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream a direct/Pixeldrain video URL through VLC.")
    parser.add_argument("url", nargs="?")
    parser.add_argument("--vlc-path")
    parser.add_argument("--keep-cache", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--list-providers", action="store_true")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.url and not args.list_providers:
        parser.error("url is required unless --list-providers is used")
    try:
        return run(args)
    except StreamError as exc:
        print(f"streamcli: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
