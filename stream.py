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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import providers
from providers import ResolvedStream, StreamError, header_int, http_request, resolve


CHUNK_SIZE = 1024 * 1024
BROWSER_PAGE = b"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StreamingCLI</title>
<link href="https://unpkg.com/video.js@8.23.9/dist/video-js.min.css" rel="stylesheet">
<style>
*{box-sizing:border-box}html,body,main{width:100%;height:100%;margin:0}
body{overflow:hidden;background:#08090a;color:#f5f7f8;font-family:Inter,ui-sans-serif,system-ui,sans-serif;letter-spacing:0}
.player-shell{position:relative;width:100%;height:100%;background:#000}
.video-js,.native-player{width:100%;height:100%;font-family:inherit}.video-js .vjs-tech,.native-player{object-fit:contain}
.brand{position:absolute;z-index:2;top:18px;left:20px;display:flex;align-items:center;gap:9px;font-size:13px;font-weight:700;pointer-events:none;text-shadow:0 1px 4px #000}
.brand-mark{width:9px;height:9px;border-radius:50%;background:#34d399;box-shadow:0 0 0 4px rgb(52 211 153/.18)}
.playback-error{position:absolute;z-index:3;left:50%;top:20px;translate:-50% 0;max-width:min(90vw,620px);padding:10px 14px;border:1px solid #713b42;border-radius:6px;background:#241316;color:#fecdd3;font-size:13px;text-align:center}
.video-js .vjs-control-bar{height:4rem;padding:0 10px;background:rgb(8 9 10/.92);align-items:center}
.video-js .vjs-progress-control{position:absolute;left:12px;right:12px;top:-13px;width:auto;height:20px}
.video-js .vjs-progress-holder{height:4px;margin:0}.video-js .vjs-progress-control:hover .vjs-progress-holder{font-size:1em;height:6px}
.video-js .vjs-play-progress,.video-js .vjs-volume-level{background:#34d399}.video-js .vjs-play-progress:before{color:#34d399}
.video-js .vjs-big-play-button{top:50%;left:50%;width:68px;height:68px;margin:-34px 0 0 -34px;border:1px solid rgb(255 255 255/.5);border-radius:50%;background:rgb(8 9 10/.78);line-height:66px}
.video-js:hover .vjs-big-play-button,.video-js .vjs-big-play-button:focus{border-color:#34d399;background:#111816}
.video-js .vjs-control:focus-visible{outline:2px solid #34d399;outline-offset:-3px}
@media(max-width:640px){.brand{top:12px;left:14px}.video-js .vjs-control-bar{height:3.5rem;padding:0 4px}.video-js .vjs-control{width:3.5em}.video-js .vjs-remaining-time{display:none}}
</style>
</head>
<body>
<main><div class="player-shell">
<div class="brand"><span class="brand-mark"></span>StreamingCLI</div>
<div id="playback-error" class="playback-error" role="alert" hidden>This browser cannot decode the video format. Try Video Player mode.</div>
<video id="streamingcli-player" class="video-js vjs-big-play-centered" controls preload="auto" playsinline>
<source src="/video">
<p class="vjs-no-js">JavaScript is disabled. Use a browser with HTML5 video support.</p>
</video>
</div></main>
<script src="https://unpkg.com/video.js@8.23.9/dist/video.min.js"></script>
<script>
const media=document.getElementById('streamingcli-player');
const error=document.getElementById('playback-error');
if(window.videojs){
  const player=videojs(media,{autoplay:true,fill:true,playbackRates:[.5,.75,1,1.25,1.5,2],userActions:{hotkeys:true}});
  player.on('error',()=>{error.hidden=false});
  player.on('loadstart',()=>{error.hidden=true});
}else{
  media.className='native-player';
  media.autoplay=true;
  media.src='/video';
  media.addEventListener('error',()=>{error.hidden=false});
}
</script>
</body>
</html>"""


class RangeCache:
    def __init__(self, path: Path):
        self.path = path
        self.intervals: list[tuple[int, int]] = []
        self.lock = threading.Lock()
        self.file = self.path.open("w+b")

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
            self.file.seek(offset)
            self.file.write(data)
            self.file.flush()
        self.add(offset, offset + len(data) - 1)

    def close(self) -> None:
        self.file.close()

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
        server_version = "StreamingCLI/0.4"

        def log_message(self, fmt, *args):
            if not quiet:
                print(f"[proxy] {self.address_string()} {fmt % args}")

        def do_HEAD(self):
            self.serve(head_only=True)

        def do_GET(self):
            self.serve(head_only=False)

        def serve(self, head_only: bool) -> None:
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(BROWSER_PAGE)))
                self.end_headers()
                if not head_only:
                    self.wfile.write(BROWSER_PAGE)
                return
            if path != "/video":
                self.send_error(404)
                return
            requested = parse_range(self.headers.get("Range"), stream.length)
            if head_only:
                if requested and stream.supports_range:
                    start, end = requested
                    total = stream.length if stream.length is not None else "*"
                    self.common_headers(206, end - start + 1, f"bytes {start}-{end}/{total}")
                else:
                    self.common_headers(200, stream.length)
                return
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


def find_player(custom_path: Optional[str], content_type: str, url: str) -> tuple[list[str], str, bool]:
    custom_path = custom_path or os.environ.get("STREAMINGCLI_PLAYER")
    if custom_path:
        if sys.platform == "darwin" and (custom_path.endswith(".app") or Path(f"/Applications/{custom_path}.app").exists() or Path(f"/System/Applications/{custom_path}.app").exists()):
            return ["open", "-W", "-a", custom_path, url], Path(custom_path).stem, True
        executable = str(Path(custom_path).expanduser()) if Path(custom_path).expanduser().exists() else shutil.which(custom_path)
        if not executable:
            raise StreamError(f"Video player not found: {custom_path}")
        return [executable, url], Path(executable).stem, True

    candidates = [shutil.which("mpv"), shutil.which("vlc"), shutil.which("ffplay")]
    if sys.platform == "darwin":
        candidates = [
            "/Applications/IINA.app/Contents/MacOS/iina-cli",
            *candidates,
            "/Applications/VLC.app/Contents/MacOS/VLC",
        ]
        if "matroska" not in content_type:
            candidates.append("/System/Applications/QuickTime Player.app/Contents/MacOS/QuickTime Player")
    if sys.platform.startswith("win"):
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if root:
                candidates.append(str(Path(root) / "VideoLAN" / "VLC" / "vlc.exe"))
    for path in candidates:
        if path and Path(path).exists():
            if "QuickTime Player" in path:
                return ["open", "-W", "-a", "QuickTime Player", url], "QuickTime Player", True
            return [path, url], Path(path).stem, True

    if sys.platform == "darwin":
        return ["open", "-W", url], "default macOS app", True
    if sys.platform.startswith("win"):
        return ["cmd", "/c", "start", "", url], "default Windows app", False
    opener = shutil.which("xdg-open")
    if opener:
        return [opener, url], "default system app", False
    raise StreamError("Video player not found. Use --player /path/to/player.")


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
    cache = None

    def cleanup():
        if server:
            server.shutdown()
            server.server_close()
        if cache:
            cache.close()
        if not args.keep_cache:
            shutil.rmtree(temp_dir, ignore_errors=True)
        elif not args.quiet:
            print(f"[streamcli] cache kept: {temp_dir}")

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    cache = RangeCache(temp_dir / "video.cache")
    server, local_url = start_server(stream, cache, args.port, args.quiet)
    if args.browser:
        browser_url = local_url.rsplit("/", 1)[0] + "/"
        print(f"[streamcli] watch in browser: {browser_url}")
        if not webbrowser.open(browser_url):
            print("[streamcli] could not open the browser automatically")
        print("[streamcli] press Ctrl+C to stop streaming")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            return 0

    command, player_name, wait_for_player = find_player(args.player or args.vlc_path, stream.content_type, local_url)
    if not args.quiet:
        print(f"[streamcli] opening {player_name}: {local_url}")
        if not wait_for_player:
            print("[streamcli] press Ctrl+C when you are done watching")
    player = subprocess.Popen(command)
    try:
        while not wait_for_player or player.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        if player.poll() is None:
            player.terminate()
        return 0
    return player.returncode or 0


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
        assert b"unpkg.com/video.js@8.23.9" in BROWSER_PAGE
        assert b'<source src="/video">' in BROWSER_PAGE
        cache.close()
    providers.self_test()
    print("self-test ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream a video URL in your preferred video player or browser.")
    parser.add_argument("url", nargs="?")
    parser.add_argument("--browser", action="store_true", help="open the stream in your web browser")
    parser.add_argument("--player", help="video player command or executable path")
    parser.add_argument("--vlc-path", help=argparse.SUPPRESS)
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
