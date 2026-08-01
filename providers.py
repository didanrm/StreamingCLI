from __future__ import annotations

import ast
import base64
import html.parser
import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional


USER_AGENT = "StreamingCLI/0.3"
SUPPORTED_PROVIDERS = ("acefile", "direct", "filedon", "krakenfiles", "pixeldrain")
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
        raise StreamError("Pixeldrain URL does not contain a file ID.")
    file_id = match.group(1)
    direct_url = f"https://pixeldrain.com/api/file/{file_id}"
    length, content_type, supports_range = None, "application/octet-stream", True

    try:
        with http_request(f"https://pixeldrain.com/api/file/{file_id}/info") as response:
            info = json.loads(response.read().decode())
            if not info.get("success", True):
                raise StreamError(info.get("message", "Pixeldrain rejected this file."))
            if info.get("can_download") is False:
                raise StreamError(info.get("availability_message") or "This Pixeldrain file cannot be downloaded.")
            length = info.get("size")
            content_type = info.get("mime_type") or content_type
    except StreamError:
        raise
    except Exception:
        length, content_type, supports_range = probe(direct_url)

    return ResolvedStream(direct_url, "pixeldrain", length=length, content_type=content_type, supports_range=supports_range)


def unpack_packer(source: str) -> str:
    match = re.search(
        r"eval\(function\(p,a,c,k,e,d\).*?\}\('((?:\\.|[^'])*)',(\d+),\d+,'((?:\\.|[^'])*)'\.split\('\|'\),0,\{\}\)\)",
        source,
        re.S,
    )
    if not match:
        raise StreamError("Acefile player configuration not found.")
    payload = ast.literal_eval(f"'{match.group(1)}'")
    radix = int(match.group(2))
    symbols = ast.literal_eval(f"'{match.group(3)}'").split("|")
    digits = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if radix > len(digits):
        raise StreamError("This Acefile player format is not supported.")

    def encoded(number: int) -> str:
        result = ""
        while number:
            number, remainder = divmod(number, radix)
            result = digits[remainder] + result
        return result or "0"

    replacements = {encoded(i): value for i, value in enumerate(symbols) if value}
    return re.sub(r"\b\w+\b", lambda found: replacements.get(found.group(0), found.group(0)), payload)


def resolve_acefile(url: str) -> ResolvedStream:
    match = re.search(r"acefile\.co/(?:f|player)/(\d+)", url)
    if not match:
        raise StreamError("Acefile URL does not contain a file ID.")
    file_id = match.group(1)
    player_url = f"https://acefile.co/player/{file_id}"

    with http_request(player_url, {"Referer": url}) as response:
        player_page = response.read().decode(errors="ignore")
    unpacked = unpack_packer(player_page)
    key_match = re.search(r'var nfck="([^"]+)"', unpacked)
    mirrors_match = re.search(r"var DUAR=(\[.*?\]);", unpacked)
    if not key_match or not mirrors_match:
        raise StreamError("Acefile mirror not found.")
    mirrors = json.loads(mirrors_match.group(1))
    if not mirrors or not mirrors[0].get("id"):
        raise StreamError("No Acefile mirror is available.")

    mirror_url = f"https://acefile.co/local/{mirrors[0]['id']}?key={key_match.group(1)}"
    with http_request(mirror_url, {"Referer": player_url}) as response:
        mirror_page = response.read().decode(errors="ignore")
    sources_match = re.search(r'sources:\s*JSON\.parse\(atob\("([^"]+)"\)\)', mirror_page)
    if not sources_match:
        raise StreamError("Acefile requires login or no mirror is available.")
    sources = json.loads(base64.b64decode(sources_match.group(1)))
    source = next((item.get("file") for item in sources if item.get("file")), None)
    if not source:
        raise StreamError("Acefile video URL not found.")

    direct_url = urllib.parse.urljoin(mirror_url, source)
    headers = {"Referer": mirror_url}
    length, content_type, supports_range = probe(direct_url, headers)
    return ResolvedStream(direct_url, "acefile", headers=headers, length=length, content_type=content_type, supports_range=supports_range)


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
        raise StreamError("The KrakenFiles link requires a captcha/login or the file is unavailable.")
    raise StreamError("No direct KrakenFiles download was found on this page.")


def resolve_filedon(url: str) -> ResolvedStream:
    match = re.search(r"filedon\.co/(?:view|embed)/([^/?#]+)", url)
    if not match:
        raise StreamError("FileDon URL does not contain a file slug.")
    slug = match.group(1)
    page_url = f"https://filedon.co/view/{slug}"

    with http_request(page_url) as response:
        page = response.read().decode(errors="ignore")
    page_match = re.search(r'data-page="([^"]+)"', page)
    if not page_match:
        raise StreamError("FileDon data was not found on this page.")

    data = json.loads(html.unescape(page_match.group(1)))
    props = data.get("props", {})
    sharing = props.get("sharing_meta", {})
    if sharing.get("is_expired") or sharing.get("limit_reached") or sharing.get("allow_download") is False:
        raise StreamError("The FileDon link expired, reached its limit, or has downloads disabled.")

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
        raise StreamError("FileDon did not return a direct download URL.")

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
    if "acefile.co" in host:
        return resolve_acefile(url)
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
    packed = "eval(function(p,a,c,k,e,d){}('0 1=\"2\";0 3=[{\"4\":\"5\"}];',6,6,'var|nfck|token|DUAR|id|42'.split('|'),0,{}))"
    assert unpack_packer(packed) == 'var nfck="token";var DUAR=[{"id":"42"}];'
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

        encoded_sources = base64.b64encode(b'[{"file":"/service/play/x","type":"mp4"}]').decode()

        def fake_acefile_request(url, *_args, **_kwargs):
            if "/player/" in url:
                return FakeResponse(packed.encode())
            return FakeResponse(f'sources: JSON.parse(atob("{encoded_sources}"))'.encode())

        globals()["http_request"] = fake_acefile_request
        stream = resolve_acefile("https://acefile.co/f/1/example-mkv")
        assert stream.url == "https://acefile.co/service/play/x"
        assert stream.provider == "acefile"
        assert stream.supports_range
    finally:
        globals()["http_request"], globals()["probe"] = old_http_request, old_probe
