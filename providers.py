from __future__ import annotations

import html.parser
import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional


USER_AGENT = "StreamCLI/0.1"
SUPPORTED_PROVIDERS = ("direct", "filedon", "krakenfiles", "pixeldrain")
COOKIE_JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIE_JAR))


@dataclass
class ResolvedStream:
    url: str
    provider: str
    headers: dict[str, str] = field(default_factory=dict)
    length: Optional[int] = None
    content_type: str = "application/octet-stream"
    supports_range: bool = False


class StreamError(Exception):
    pass


def http_request(url: str, headers: Optional[dict[str, str]] = None, method: str = "GET", data: Optional[bytes] = None):
    req_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    return OPENER.open(urllib.request.Request(url, data=data, headers=req_headers, method=method), timeout=30)


def header_int(headers, name: str) -> Optional[int]:
    value = headers.get(name)
    return int(value) if value and value.isdigit() else None


def parse_total_from_content_range(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = re.search(r"/(\d+)$", value)
    return int(match.group(1)) if match else None


def probe(url: str, headers: Optional[dict[str, str]] = None) -> tuple[Optional[int], str, bool]:
    length = None
    content_type = "application/octet-stream"
    supports_range = False

    try:
        with http_request(url, headers, "HEAD") as response:
            length = header_int(response.headers, "Content-Length")
            content_type = response.headers.get("Content-Type", content_type).split(";")[0]
            supports_range = "bytes" in response.headers.get("Accept-Ranges", "").lower()
    except Exception:
        pass

    try:
        range_headers = {**(headers or {}), "Range": "bytes=0-0"}
        with http_request(url, range_headers) as response:
            supports_range = response.status == 206 or supports_range
            length = parse_total_from_content_range(response.headers.get("Content-Range")) or length
            content_type = response.headers.get("Content-Type", content_type).split(";")[0]
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 404, 416):
            raise
    except Exception:
        pass

    return length, content_type, supports_range


def resolve_pixeldrain(url: str) -> ResolvedStream:
    match = re.search(r"pixeldrain\.com/(?:u|file)/([^/?#]+)", url)
    if not match:
        raise StreamError("Pixeldrain URL tidak berisi file id.")
    file_id = match.group(1)
    direct_url = f"https://pixeldrain.com/api/file/{file_id}"
    length, content_type, supports_range = probe(direct_url)

    try:
        with http_request(f"https://pixeldrain.com/api/file/{file_id}/info") as response:
            info = json.loads(response.read().decode())
            if not info.get("success", True):
                raise StreamError(info.get("message", "Pixeldrain menolak file ini."))
            length = info.get("size") or length
            content_type = info.get("mime_type") or content_type
    except StreamError:
        raise
    except Exception:
        pass

    return ResolvedStream(direct_url, "pixeldrain", length=length, content_type=content_type, supports_range=supports_range)


class DownloadLinkParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.media: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "source" and attrs.get("src") and "video/" in attrs.get("type", ""):
            self.media.append(attrs["src"])
            return
        href = attrs.get("href") if tag == "a" else attrs.get("action") if tag == "form" else None
        marker = " ".join(str(v) for v in attrs.values()).lower()
        if href and ("download" in marker or "/download/" in href):
            self.links.append(href)


def resolve_krakenfiles(url: str) -> ResolvedStream:
    with http_request(url) as response:
        html = response.read().decode(errors="ignore")

    parser = DownloadLinkParser()
    parser.feed(html)
    candidates = parser.media + parser.links + re.findall(r"https?://[^\"'<>\\]+/download/[^\"'<>\\]+", html)
    for candidate in dict.fromkeys(urllib.parse.urljoin(url, c) for c in candidates):
        headers = {"Referer": url}
        try:
            length, content_type, supports_range = probe(candidate, headers)
        except urllib.error.HTTPError as exc:
            if exc.code == 405:
                continue
            raise
        if content_type not in ("text/html", "application/xhtml+xml"):
            return ResolvedStream(candidate, "krakenfiles", headers=headers, length=length, content_type=content_type, supports_range=supports_range)

    if re.search(r"captcha|cf-turnstile|login|private|not found|file removed", html, re.I):
        raise StreamError("KrakenFiles link butuh captcha/login atau file tidak tersedia.")
    raise StreamError("Tidak menemukan direct download KrakenFiles di halaman ini.")


def resolve_filedon(url: str) -> ResolvedStream:
    match = re.search(r"filedon\.co/(?:view|embed)/([^/?#]+)", url)
    if not match:
        raise StreamError("FileDon URL tidak berisi file slug.")
    slug = match.group(1)
    page_url = f"https://filedon.co/view/{slug}"

    with http_request(page_url) as response:
        page = response.read().decode(errors="ignore")
    page_match = re.search(r'data-page="([^"]+)"', page)
    if not page_match:
        raise StreamError("Tidak menemukan data FileDon di halaman ini.")

    data = json.loads(html.unescape(page_match.group(1)))
    props = data.get("props", {})
    sharing = props.get("sharing_meta", {})
    if sharing.get("is_expired") or sharing.get("limit_reached") or sharing.get("allow_download") is False:
        raise StreamError("FileDon link expired, limit tercapai, atau download dimatikan.")

    csrf = props.get("flash", {}).get("_token")
    if not csrf:
        meta = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
        csrf = meta.group(1) if meta else ""

    headers = {
        "Accept": "text/html, application/xhtml+xml",
        "Content-Type": "application/json",
        "Referer": page_url,
        "X-CSRF-TOKEN": csrf,
        "X-Inertia": "true",
        "X-Inertia-Version": data.get("version", ""),
        "X-Requested-With": "XMLHttpRequest",
    }
    with http_request(f"https://filedon.co/download/{slug}", headers, "POST", b"{}") as response:
        download_data = json.loads(response.read().decode())

    direct_url = download_data.get("props", {}).get("flash", {}).get("download_url")
    if not direct_url:
        raise StreamError("FileDon tidak mengirim direct download URL.")

    file_info = props.get("files", {})
    found_length, found_type, supports_range = probe(direct_url)
    return ResolvedStream(
        direct_url,
        "filedon",
        length=file_info.get("size") or found_length,
        content_type=file_info.get("mime_type") or found_type,
        supports_range=supports_range,
    )


def resolve_direct(url: str) -> ResolvedStream:
    length, content_type, supports_range = probe(url)
    return ResolvedStream(url, "direct", length=length, content_type=content_type, supports_range=supports_range)


def resolve(url: str) -> ResolvedStream:
    host = urllib.parse.urlparse(url).netloc.lower()
    if "pixeldrain.com" in host:
        return resolve_pixeldrain(url)
    if "filedon.co" in host:
        return resolve_filedon(url)
    if "krakenfiles.com" in host:
        return resolve_krakenfiles(url)
    return resolve_direct(url)


def self_test() -> None:
    parser = DownloadLinkParser()
    parser.feed('<a class="download" href="/download/abc/file.mp4">Download</a>')
    assert parser.links == ["/download/abc/file.mp4"]
    parser.feed('<source src="/play/video/abc" type="video/mp4"><a href="/login">Log In</a>')
    assert parser.media == ["/play/video/abc"]
    page = '<div data-page="{&quot;props&quot;:{&quot;files&quot;:{&quot;size&quot;:9,&quot;mime_type&quot;:&quot;video/mp4&quot;},&quot;flash&quot;:{&quot;_token&quot;:&quot;t&quot;},&quot;sharing_meta&quot;:{&quot;allow_download&quot;:true}},&quot;version&quot;:&quot;v&quot;}"></div>'
    assert json.loads(html.unescape(re.search(r'data-page="([^"]+)"', page).group(1)))["version"] == "v"
    old_http_request, old_probe = globals()["http_request"], globals()["probe"]

    class FakeResponse:
        def __init__(self, body=b'<a href="/login">Log In</a><source src="/play/video/abc" type="video/mp4"><a class="download" href="/download/abc/file.mp4">Download</a>'):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return self.body

    try:
        globals()["http_request"] = lambda *_args, **_kwargs: FakeResponse()
        globals()["probe"] = lambda url, headers=None: (123, "video/mp4", True)
        stream = resolve_krakenfiles("https://krakenfiles.com/view/abc/file.html")
        assert stream.url == "https://krakenfiles.com/play/video/abc"
        assert stream.provider == "krakenfiles"
        assert stream.supports_range

        def fake_filedon_request(_url, _headers=None, method="GET", _data=None):
            if method == "POST":
                return FakeResponse(b'{"props":{"flash":{"download_url":"https://cdn.example/video.mkv"}}}')
            return FakeResponse(page.encode())

        globals()["http_request"] = fake_filedon_request
        stream = resolve_filedon("https://filedon.co/view/o5EZpGdUGY")
        assert stream.url == "https://cdn.example/video.mkv"
        assert stream.provider == "filedon"
        assert stream.length == 9
        assert stream.content_type == "video/mp4"
    finally:
        globals()["http_request"], globals()["probe"] = old_http_request, old_probe
